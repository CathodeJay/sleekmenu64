
#include "appmain.h"

#define STATUS_KEY              0x5A
#define PROTOCOL_ID             0x07
//****************************************************************************** base cmd
#define CMD_STATUS              0x10
#define CMD_GET_MODE            0x11
#define CMD_IO_RST              0x12
#define CMD_NRESP               0x13
//****************************************************************************** CMD_FS
#define CMD_FS                  0x80
#define FS_SCMD_INIT            0x10
#define FS_SCMD_DIR_OPN         0x11
#define FS_SCMD_DIR_RD          0x12
#define FS_SCMD_DIR_LD          0x13
#define FS_SCMD_DIR_SIZE        0x14
#define FS_SCMD_DIR_PATH        0x15
#define FS_SCMD_DIR_GET         0x16
#define FS_SCMD_FOPN            0x17
#define FS_SCMD_FCLOSE          0x18
#define FS_SCMD_FPTR            0x19
#define FS_SCMD_FINFO           0x1A
#define FS_SCMD_FCRC            0x1B
#define FS_SCMD_DIR_MK          0x1C
#define FS_SCMD_DEL             0x1D
#define FS_SCMD_SEEK_IDX        0x1E
#define FS_SCMD_AVB             0x1F
#define FS_SCMD_FCP             0x20
#define FS_SCMD_SEEK_PAT        0x21 //seek data pattern
#define FS_SCMD_DTEST           0x22 //check if dir exists
#define FS_SCMD_FTEST           0x23 //check if file exists
//****************************************************************************** CMD_EPO
#define CMD_EPO                 0x81
#define EPO_SCMD_XFER           0x10
#define EPO_SCMD_MSR            0x11 //one time wr enable for protected memory

#define EPO_TYPE_LINK           0x10 //link (usb or console)
#define EPO_TYPE_LINK_ACK       0x11 //link (usb or console 1k blocks)
#define EPO_TYPE_FS             0x12 //file
#define EPO_TYPE_FCI            0x13 //ed mem
#define EPO_TYPE_FLA            0x14 //mcu flash
#define EPO_TYPE_RAM            0x15 //ram buffer
#define EPO_TYPE_NOP            0x16
#define EPO_TYPE_DBG            0x17 //uart debug port
#define EPO_TYPE_USB            0x18
//****************************************************************************** CMD_FCI
#define CMD_FCI                 0x82
#define FCI_SCMD_MEM_SET        0x10
#define FCI_SCMD_MEM_TST        0x11
#define FCI_SCMD_MEM_CRC        0x12
//****************************************************************************** CMD_RTC
#define CMD_RTC                 0x83
#define RTC_SCMD_GET            0x10
#define RTC_SCMD_SET            0x11
#define RTC_SCMD_CAL            0x12
//****************************************************************************** CMD_SYS
#define CMD_SYS                 0x84
#define SYS_SCMD_GET_INF        0x10
#define SYS_SCMD_RESET          0x11
#define SYS_SCMD_FPG_INIT       0x12
#define SYS_SCMD_EFU_INSTALL    0x13
#define SYS_SCMD_BOOT_UPD       0x14
#define SYS_SCMD_SISTAT         0x15
//****************************************************************************** CMD_DEV
#define CMD_DEV                 0x85
#define DEV_SCMD_STOP           0x10
#define DEV_SCMD_START          0x11
#define DEV_SCMD_GAME_CTR       0x12

#define DEV_SCMD_SET_CFG        0x20
#define DEV_SCMD_SET_PATH       0x21
#define DEV_SCMD_GET_PATH       0x22
#define DEV_SCMD_WR_SWAP        0x23
#define DEV_SCMD_XPS            0x24
#define DEV_SCMD_CIC_UPD        0x25
#define DEV_SCMD_BRM_RMAP       0x26
#define DEV_SCMD_HAN_STAT       0x27
//****************************************************************************** CMD_BOOT
#define CMD_BOOT                0xF0
#define BOOT_SCMD_APP_MODE      0x10
#define BOOT_SCMD_LOAD_APP      0x11
#define BOOT_SCMD_GET_UID64     0x12
#define BOOT_SCMD_GET_UID128    0x13
#define BOOT_SCMD_GET_SIGNA     0x14
#define BOOT_SCMD_SET_SIGNA     0x15
#define BOOT_SCMD_MCU_SECURE    0x16
//******************************************************************************
#define SIZE_ACK_BLOCK          1024

#define SYSSTAT_BUSY            (1 << 0) // ro mcu busy ststus
#define SYSSTAT_WAIT_MCU        (1 << 1) // rw clears when mcu finished cmd
#define SYSSTAT_WAIT_FPG        (1 << 2) // rw clears after fpga reinit
#define SYSSTAT_STROBE          (1 << 3) // ro inverts after each rd operation
#define SYSSTAT_CMSK            0xF0
#define SYSSTAT_CVAL            0xA0     // ro const value

#define RTCC_SET_TIME           0
#define RTCC_CAL_START          1
#define RTCC_CAL_END            2
#define RTCC_GET_CURCAL         3
#define RTCC_GET_ESTCAL         4
#define RTCC_GET_DEVIAT         5

#define MBX_READY               0x52445921

typedef u8 EpoType;

typedef struct {
    u32 src_addr;
    u32 dst_addr;
    u32 len;
    EpoType src_type;
    EpoType dst_type;
    u16 reserved;
} EpoXfer;
//******************************************************************************
u32 ed_reg_rd(vu32 *reg);
void ed_reg_wr(vu32 *reg, u32 val);
void ed_fifo_wr(void *src, u32 len);
u8 ed_fifo_rd_skip(u32 len);
void ed_cmd_status(void *status);
u8 ed_sysstat();

u32 max_ed(u32 v1, u32 v2) {
    if (v1 > v2)return v1;
    return v2;
}

u32 min_ed(u32 v1, u32 v2) {
    if (v1 < v2)return v1;
    return v2;
}

u8 ed_init_hw() {

    u8 resp;

    resp = ed_dev_stop(1);
    if (resp)return resp;

    return 0;
}

u32 ed_reg_rd(vu32 *reg) {

    static u32 rx_val __attribute__((aligned(8)));

    pi_rd(&rx_val, (u32) reg, 4);
    return rx_val;
}

void ed_reg_wr(vu32 *reg, u32 val) {

    static u32 tx_val __attribute__((aligned(8)));

    tx_val = val;
    pi_wr(&tx_val, (u32) reg, 4);
}

void ed_reg_rd_stream(vu32 *reg, void *dst, u32 len) {

    static u32 buff[128]__attribute__((aligned(512)));

    while (len) {

        u32 block = min_ed(len, sizeof (buff) / 4);

        pi_rd(buff, (u32) reg, block * 4);

        for (int i = 0; i < block; i++) {
            *(u8 *) dst++ = buff[i];
        }

        len -= block;
    }
}

void ed_reg_wr_stream(vu32 *reg, void *src, u32 len) {

    static u32 buff[128]__attribute__((aligned(512)));

    while (len) {

        u32 block = min_ed(len, sizeof (buff) / 4);

        for (int i = 0; i < block; i++) {
            buff[i] = *(u8 *) src++;
        }

        pi_wr(buff, (u32) reg, block * 4);

        len -= block;
    }
}

u32 ed_fifo_avb() {

    return ed_reg_rd(&EDIO->FIFOSTAT) & 0xffff;
}

void ed_fifo_flush() {
    ed_fifo_rd_skip(ed_fifo_avb());
}

u32 ed_fifo_rda(void *dst, u32 len) {

    u32 block = min_ed(len, ed_fifo_avb());

    ed_reg_rd_stream(&EDIO->FIFODATA, dst, block);

    return block;
}

void ed_fifo_rd(void *dst, u32 len) {

    while (len) {

        u32 block = ed_fifo_rda(dst, len);
        len -= block;
        dst += block;
    }
}

u8 ed_fifo_rd_ack(void *dst, u32 len) {

    u8 resp = 0;
    u8 ack = 0;

    while (len) {

        u32 block = min_ed(SIZE_ACK_BLOCK, len);

        ed_fifo_wr(&ack, 1);
        //resp = ed_fifo_rd_to(dst, block);
        ed_fifo_rd(dst, block);

        dst += block;
        len -= block;
    }

    return resp;
}

u8 ed_fifo_rd_skip(u32 len) {

    u8 buff[512];

    while (len) {

        u32 block = min_ed(len, sizeof (buff));
        ed_fifo_rd(buff, block);
        len -= block;
    }

    return 0;
}

void ed_fifo_wr(void *src, u32 len) {

    ed_reg_wr_stream(&EDIO->FIFODATA, src, len);
}

u8 ed_fifo_wr_ack(void *src, u32 len) {

    u8 ack = 0;

    while (len) {

        u32 block = min_ed(SIZE_ACK_BLOCK, len);

        //resp = ed_fifo_rd_to(&ack, 1);
        ed_fifo_rd(&ack, 1);
        ed_fifo_wr(src, block);

        src += block;
        len -= block;
    }

    return 0;
}

void ed_cmd_tx(u8 cmd) {

    u8 buff[4];

    buff[0] = '+';
    buff[1] = '+' ^ 0xff;
    buff[2] = cmd;
    buff[3] = cmd ^ 0xff;

    ed_fifo_wr(buff, sizeof (buff));
}

void ed_scmd_tx(u8 cmd, u8 scmd) {

    u8 buff[5];

    buff[0] = '+';
    buff[1] = '+' ^ 0xff;
    buff[2] = cmd;
    buff[3] = cmd ^ 0xff;
    buff[4] = scmd;

    ed_fifo_wr(buff, sizeof (buff));
}

void ed_tx_string(u8 *string) {

    u16 str_len = 0;
    u8 *ptr = string;

    while (*ptr++ != 0) {
        str_len++;
    }

    ed_fifo_wr(&str_len, 2);
    ed_fifo_wr(string, str_len);
}

void ed_rx_string(u8 *string) {

    u16 str_len;

    ed_fifo_rd(&str_len, 2);

    if (string == 0) {
        ed_fifo_rd_skip(str_len);
        return;
    }

    string[str_len] = 0;

    ed_fifo_rd(string, str_len);
}

void ed_run_xfer() {

    u8 ack = 0;
    ed_fifo_wr(&ack, 1);
}

void ed_wait_mcu() {
    while ((ed_reg_rd(&EDIO->SYSSTAT) & SYSSTAT_BUSY) != 0);
}
//******************************************************************************

u32 ed_get_cart_id() {

    return ed_reg_rd(&EDIO->EDID);
}

void ed_cmd_status(void *status) {

    ed_cmd_tx(CMD_STATUS);
    ed_fifo_rd(status, 4);
}

u8 ed_check_status() {

    u8 resp[4];

    ed_cmd_status(resp);

    if (resp[0] != STATUS_KEY) {
        return ERR_UNXP_STAT;
    }

    return resp[3];
}

u8 ed_cmd_nresp(u8 resp) {

    u8 nresp;
    ed_cmd_tx(CMD_NRESP);
    ed_fifo_wr(&resp, 1);
    ed_fifo_rd(&nresp, 1);
    return nresp;
}

void ed_cmd_epo_xfer(EpoXfer *xfer) {

    ed_scmd_tx(CMD_EPO, EPO_SCMD_XFER);
    ed_fifo_wr(xfer, sizeof (EpoXfer));
    ed_run_xfer();
}

u8 ed_epo_wr(u32 addr, void *src, u32 len, EpoType epo) {

    while (len) {

        u32 block = min_ed(len, SIZE_ACK_BLOCK);

        EpoXfer xfer = {
            .src_type = EPO_TYPE_LINK, .src_addr = 0,
            .dst_type = epo, .dst_addr = addr,
            .len = block
        };

        ed_cmd_epo_xfer(&xfer);

        ed_fifo_wr(src, block);

        ed_wait_mcu();

        len -= block;
        src += block;
        addr += len;
    }

    return 0;
}

u8 ed_epo_rd(u32 addr, void *dst, u32 len, EpoType epo) {

    while (len) {

        u32 block = min_ed(len, SIZE_ACK_BLOCK);

        EpoXfer xfer = {
            .src_type = epo, .src_addr = addr,
            .dst_type = EPO_TYPE_LINK, .dst_addr = 0,
            .len = block
        };


        ed_cmd_epo_xfer(&xfer);

        ed_fifo_rd(dst, block);

        len -= block;
        dst += block;
        addr += len;
    }

    return 0;
}
//******************************************************************************

u8 ed_usb_wr_fci(u32 src, u32 len) {

    EpoXfer xfer = {
        .src_type = EPO_TYPE_FCI, .src_addr = src,
        .dst_type = EPO_TYPE_USB, .dst_addr = 0,
        .len = len
    };

    ed_cmd_epo_xfer(&xfer);
    ed_wait_mcu();

    return 0;
}

u8 ed_usb_wr(void *src, u32 len) {
    return ed_epo_wr(0, src, len, EPO_TYPE_USB);
}

u8 ed_urt_wr(u8 *src, u32 len) {
    return ed_epo_wr(0, src, len, EPO_TYPE_DBG);
}

int ed_dbg_wr_urt(char *buf, unsigned int len) {
    //onboard uart port (921600)
    ed_urt_wr((u8 *) buf, len);
    return len;
}

int ed_dbg_wr_usb(char *buf, unsigned int len) {
    ed_usb_wr((u8 *) buf, len);
    return len;
}

void ed_mbx_wr(u32 val) {
    ed_reg_wr(&EDIO->MBX, val);
}

u32 ed_mbx_rd() {

    while (1) {
        u32 v1 = ed_reg_rd(&EDIO->MBX);
        u32 v2 = ed_reg_rd(&EDIO->MBX);
        if (v1 == v2) {
            return v1;
        }
    }
}

void ed_mbx_reset() {
    ed_mbx_wr(0);
}

void ed_mbx_busy() {
    while (ed_mbx_rd() != MBX_READY);
}
//****************************************************************************** fs

void ed_fs_rx_file_info(FileInfo *inf) {

    ed_fifo_rd(inf, 9);
    ed_rx_string(inf->file_name);
    inf->is_dir &= AT_DIR;
}

u8 ed_fs_rx_next_rec(FileInfo *inf) {

    u8 resp;

    ed_fifo_rd(&resp, 1);
    if (resp)return resp;

    ed_fs_rx_file_info(inf);

    return 0;
}

u8 ed_fs_init() {

    ed_scmd_tx(CMD_FS, FS_SCMD_INIT);
    return ed_check_status();
}

u8 ed_fs_file_open(u8 *path, u8 mode) {

    if (*path == 0) {
        return ERR_NULL_PATH;
    }

    ed_scmd_tx(CMD_FS, FS_SCMD_FOPN);
    ed_fifo_wr(&mode, 1);
    ed_tx_string(path);

    return ed_check_status();
}

u8 ed_fs_file_close() {

    ed_scmd_tx(CMD_FS, FS_SCMD_FCLOSE);
    return ed_check_status();
}

u32 ed_fs_file_available() {

    u32 len[2];
    ed_scmd_tx(CMD_FS, FS_SCMD_AVB);
    ed_fifo_rd(len, 8);

    return len[0];
}

u8 ed_fs_file_read(void *dst, u32 len) {

    u8 resp;

    if (len == 0) {
        return 0;
    }

    EpoXfer xfer = {
        .src_type = EPO_TYPE_FS, .src_addr = 0,
        .dst_type = EPO_TYPE_LINK_ACK, .dst_addr = 0,
        .len = len
    };

    ed_cmd_epo_xfer(&xfer);

    resp = ed_fifo_rd_ack(dst, len);
    if (resp)return resp;

    return ed_check_status();
}

u8 ed_fs_file_read_fci(u32 addr, u32 len) {


    if (len == 0) {
        return 0;
    }

    EpoXfer xfer = {
        .src_type = EPO_TYPE_FS, .src_addr = 0,
        .dst_type = EPO_TYPE_FCI, .dst_addr = addr,
        .len = len
    };
    ed_cmd_epo_xfer(&xfer);

    return ed_check_status();
}

u8 ed_fs_file_write(void *src, u32 len) {

    u8 resp;

    if (len == 0) {
        return 0;
    }

    EpoXfer xfer = {
        .src_type = EPO_TYPE_LINK_ACK, .src_addr = 0,
        .dst_type = EPO_TYPE_FS, .dst_addr = 0,
        .len = len
    };

    ed_cmd_epo_xfer(&xfer);

    resp = ed_fifo_wr_ack(src, len);
    if (resp)return resp;

    return ed_check_status();
}

u8 ed_fs_file_write_fci(u32 addr, u32 len) {

    if (len == 0) {
        return 0;
    }

    EpoXfer xfer = {
        .src_type = EPO_TYPE_FCI, .src_addr = addr,
        .dst_type = EPO_TYPE_FS, .dst_addr = 0,
        .len = len
    };
    ed_cmd_epo_xfer(&xfer);

    return ed_check_status();
}

u8 ed_fs_file_set_ptr(u32 addr) {

    ed_scmd_tx(CMD_FS, FS_SCMD_FPTR);
    ed_fifo_wr(&addr, 4);
    return ed_check_status();
}

u8 ed_fs_file_info(u8 *path, FileInfo *inf) {

    u8 resp;

    ed_scmd_tx(CMD_FS, FS_SCMD_FINFO);
    ed_tx_string(path);

    ed_fifo_rd(&resp, 1);
    if (resp)return resp;

    ed_fs_rx_file_info(inf);

    return 0;
}

u8 ed_fs_file_del(u8 *path) {

    ed_scmd_tx(CMD_FS, FS_SCMD_DEL);
    ed_tx_string(path);
    return ed_check_status();
}

u8 ed_fs_file_crc(u32 len, u32 *crc_base) {

    u8 resp;
    ed_scmd_tx(CMD_FS, FS_SCMD_FCRC);
    ed_fifo_wr(&len, 4);
    ed_fifo_wr(crc_base, 4);

    ed_fifo_rd(&resp, 1);
    ed_fifo_rd(crc_base, 4);

    return resp;
}

u8 ed_fs_dir_make(u8 *path) {

    ed_scmd_tx(CMD_FS, FS_SCMD_DIR_MK);
    ed_tx_string(path);
    return ed_check_status();
}

u8 ed_fs_dir_load(u8 *path, u8 dir_opt) {

    ed_scmd_tx(CMD_FS, FS_SCMD_DIR_LD);
    ed_fifo_wr(&dir_opt, 1);
    ed_tx_string(path);

    return ed_check_status();
}

void ed_fs_dir_get_size(u16 *size) {

    ed_scmd_tx(CMD_FS, FS_SCMD_DIR_SIZE);
    ed_fifo_rd(size, 2);
}

void ed_fs_dir_seek_idx(u16 *idx) {

    ed_scmd_tx(CMD_FS, FS_SCMD_SEEK_IDX);
    ed_fifo_rd(idx, 2);
}

void ed_fs_dir_get_recs(u16 start_idx, u16 amount, u16 max_name_len) {
    
    ed_scmd_tx(CMD_FS, FS_SCMD_DIR_GET);
    ed_fifo_wr(&start_idx, 2);
    ed_fifo_wr(&amount, 2);
    ed_fifo_wr(&max_name_len, 2);
}

u8 ed_fs_file_copy(u8 *src, u8 *dst, u8 dst_mode) {

    ed_scmd_tx(CMD_FS, FS_SCMD_FCP);
    ed_fifo_wr(&dst_mode, 1);
    ed_tx_string(src);
    ed_tx_string(dst);
    return ed_check_status();
}

u8 ed_fs_file_seek_pat(u8 *pat, u8 psize, u32 fsize, u32 *paddr) {

    u8 resp;
    ed_scmd_tx(CMD_FS, FS_SCMD_SEEK_PAT);
    ed_fifo_wr(&fsize, 4);
    ed_fifo_wr(&psize, 1);
    ed_fifo_wr(pat, psize);

    ed_fifo_rd(&resp, 1);
    ed_fifo_rd(paddr, 4);
    return resp;
}

u8 ed_fs_file_test(u8 *path) {

    ed_scmd_tx(CMD_FS, FS_SCMD_FTEST);
    ed_tx_string(path);
    return ed_check_status();
}

u8 ed_fs_dir_test(u8 *path) {

    ed_scmd_tx(CMD_FS, FS_SCMD_DTEST);
    ed_tx_string(path);
    return ed_check_status();
}

//****************************************************************************** memory io

void ed_fci_set(u8 val, u32 addr, u32 len) {

    ed_scmd_tx(CMD_FCI, FCI_SCMD_MEM_SET);
    ed_fifo_wr(&addr, 4);
    ed_fifo_wr(&len, 4);
    ed_fifo_wr(&val, 1);
    ed_run_xfer();
}

u8 ed_fci_test(u8 val, u32 addr, u32 len) {

    u8 resp;

    ed_scmd_tx(CMD_FCI, FCI_SCMD_MEM_TST);
    ed_fifo_wr(&addr, 4);
    ed_fifo_wr(&len, 4);
    ed_fifo_wr(&val, 1);
    ed_run_xfer();
    ed_fifo_rd(&resp, 1);

    return resp;
}

void ed_fci_rd(u32 addr, void *dst, u32 len) {

    ed_epo_rd(addr, dst, len, EPO_TYPE_FCI);
}

void ed_fci_wr(u32 addr, void *src, u32 len) {

    ed_epo_wr(addr, src, len, EPO_TYPE_FCI);
}

void ed_fci_crc(u32 addr, u32 len, u32 *crc_base) {

    ed_scmd_tx(CMD_FCI, FCI_SCMD_MEM_CRC);
    ed_fifo_wr(&addr, 4);
    ed_fifo_wr(&len, 4);
    ed_fifo_wr(crc_base, 4);
    ed_run_xfer();

    ed_fifo_rd(crc_base, 4);
}
//******************************************************************************

u32 ed_get_ticks() {

    return ed_reg_rd(&EDIO->TIMER);
}

void ed_sys_get_inf(u32 *list, u8 list_len) {

    ed_scmd_tx(CMD_SYS, SYS_SCMD_GET_INF);
    ed_fifo_wr(&list_len, 1);
    ed_fifo_wr(list, list_len * 4);
    ed_fifo_rd(list, list_len * 4);
}

u8 ed_sys_reset() {

    u8 arg = 0;

    ed_mbx_reset();
    ed_scmd_tx(CMD_SYS, SYS_SCMD_RESET);
    ed_fifo_wr(&arg, 1);
    ed_mbx_busy();

    return ed_check_status();
}

u8 ed_sys_fpga_init(u32 len) {

    ed_mbx_reset();

    u8 epo = EPO_TYPE_FS;
    ed_scmd_tx(CMD_SYS, SYS_SCMD_FPG_INIT);
    ed_fifo_wr(&len, 4); //send 0 for rle datafile
    ed_fifo_wr(&epo, 1);

    ed_mbx_busy();

    return ed_check_status();
}

u8 ed_sys_efu_install(u8 *path) {

    ed_scmd_tx(CMD_SYS, SYS_SCMD_EFU_INSTALL);
    ed_tx_string(path);

    return ed_check_status();
}

u8 ed_dev_stop(u8 flush_fifo) {

    ed_mbx_reset();

    ed_scmd_tx(CMD_DEV, DEV_SCMD_STOP);

    ed_mbx_busy();

    if (flush_fifo) {
        ed_fifo_flush();
    }

    return ed_check_status();
}

u8 ed_dev_start() {

    ed_scmd_tx(CMD_DEV, DEV_SCMD_START);
    return ed_check_status();
}

void ed_dev_game_ctr() {
    ed_scmd_tx(CMD_DEV, DEV_SCMD_GAME_CTR);
}

u8 ed_dev_set_path(u8 *path, DevPathType path_type) {

    u8 type = path_type;

    ed_scmd_tx(CMD_DEV, DEV_SCMD_SET_PATH);
    ed_fifo_wr(&type, 1);
    ed_tx_string(path);

    return ed_check_status();
}

u8 ed_dev_set_cfg(DevCfg *cfg) {

    ed_scmd_tx(CMD_DEV, DEV_SCMD_SET_CFG);
    ed_fifo_wr(cfg, sizeof (DevCfg));
    return ed_check_status();
}

void ed_dev_wr_swap(u8 swap_en) {

    ed_scmd_tx(CMD_DEV, DEV_SCMD_WR_SWAP);
    ed_fifo_wr(&swap_en, 1);
}

u8 ed_dev_xps(u8 *path, u32 base_addr) {

    ed_scmd_tx(CMD_DEV, DEV_SCMD_XPS);

    ed_fifo_wr(&base_addr, 4);
    ed_tx_string(path);

    return ed_check_status();
}

u8 ed_dev_get_path(u8 *path, DevPathType path_type) {

    u8 type = path_type;

    ed_scmd_tx(CMD_DEV, DEV_SCMD_GET_PATH);
    ed_fifo_wr(&type, 1);
    ed_rx_string(path);

    return ed_check_status();
}

u8 ed_dev_brm_rmap(u32 addr) {

    ed_scmd_tx(CMD_DEV, DEV_SCMD_BRM_RMAP);
    ed_fifo_wr(&addr, 4);
    return ed_check_status();
}

void ed_dev_han_stat(HanStatus *stat) {
    ed_scmd_tx(CMD_DEV, DEV_SCMD_HAN_STAT);
    ed_fifo_rd(stat, sizeof (HanStatus));
}

void ed_rtc_get(RtcTime *rtc) {

    ed_scmd_tx(CMD_RTC, RTC_SCMD_GET);
    ed_fifo_rd(rtc, sizeof (RtcTime));
}

void ed_rtc_set(RtcTime *rtc) {

    ed_scmd_tx(CMD_RTC, RTC_SCMD_SET);
    ed_fifo_wr(rtc, sizeof (RtcTime));
}

s32 ed_rtcc_curval() {

    u8 cmd = RTCC_GET_CURCAL;
    RtcTime time = {0};
    s32 resp;

    ed_scmd_tx(CMD_RTC, RTC_SCMD_CAL);
    ed_fifo_wr(&time, sizeof (RtcTime));
    ed_fifo_wr(&cmd, 1);

    ed_fifo_rd(&resp, 4);

    return resp;
}

u8 ed_sysstat() {

    while (1) {

        u8 v1 = ed_reg_rd(&EDIO->SYSSTAT);
        u8 v2 = ed_reg_rd(&EDIO->SYSSTAT);

        if ((v1 & SYSSTAT_STROBE) == (v2 & SYSSTAT_STROBE)) {
            continue;
        }

        if ((v1 | SYSSTAT_STROBE) != (v2 | SYSSTAT_STROBE)) {
            continue;
        }

        if ((v1 & SYSSTAT_CMSK) != SYSSTAT_CVAL) {
            continue;
        }

        return v1;
    }
}

double ed_measure_fps() {

    u32 t0, t1, time;
    u32 rep = 5;
    u32 tmp = 0;

    disable_interrupts();

    pi_wr(&tmp, (u32) EDIO->MCTR, 4);
    while (VI->CURR_LINE == 0x200);
    while (VI->CURR_LINE != 0x200);

    t0 = EDIO->MCTR;

    for (int i = 0; i < rep; i++) {
        while (VI->CURR_LINE == 0x200);
        while (VI->CURR_LINE != 0x200);
    }

    t1 = EDIO->MCTR;
    time = (t1 - t0) / rep;
    time = max_ed(1, time);

    double fps = (double) MCTR_FREQ / time;

    enable_interrupts();

    return fps;
}

