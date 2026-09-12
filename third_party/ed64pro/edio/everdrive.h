/* 
 * File:   everdrive.h
 * Author: Igor
 *
 * Created on November 23, 2025, 11:29 AM
 */

#ifndef EVERDRIVE_H
#define	EVERDRIVE_H

#define DEVID_ED64PRO   0x27
//****************************************************************************** registers

typedef struct {
    vu32 FIFODATA; //   R/W Onboard mcu fifo io port
    vu32 FIFOSTAT; //   R   Fifo status
    vu32 SYSSTAT; //    R   mcu/sdc/fpga status
    vu32 TIMER; //      R   System timer, 32bit, 1ms resolution
    vu32 MBX; //        R/W Communication reg (mcu/usb <> n64)
    vu32 EDID; //       R   Device ID 0xED64xxxx
    vu32 MCTR; //       R   Hi resolution timer. 50Mhz
} Edio;

#define EDIO_BASE       (KSEG1 | 0x1F800000)
#define EDIO            ((Edio *) EDIO_BASE)

#define SYSSTAT_BTN     (1 << 16)
#define MCTR_FREQ       50000000.0
//****************************************************************************** fs

typedef struct {
    //structure size hardcoded in ed_fs_rx_file_info
    u32 size;
    u16 date; //ms dos dormat
    u16 time; //ms dos dormat
    u8 is_dir;
    u8 *file_name;
} FileInfo;

#define	FA_READ		 0x01
#define	FA_WRITE	 0x02
#define	FA_OPEN_EXISTING 0x00
#define	FA_CREATE_NEW	 0x04
#define	FA_CREATE_ALWAYS 0x08
#define	FA_OPEN_ALWAYS	 0x10
#define	FA_OPEN_APPEND	 0x30
#define FS_MAKEPATH      0x80 //make path if not exists

#define	AT_RDO          0x01    // Read only
#define	AT_HID          0x02	// Hidden
#define	AT_SYS          0x04	// System
#define AT_DIR          0x10	// Directory
#define AT_ARC          0x20	// Archive

#define DIR_OPT_SORTED  0x01
#define DIR_OPT_HIDESYS 0x02
#define DIR_OPT_SEEKCUE 0x04
#define DIR_OPT_FILTCUE 0x08
#define DIR_OPT_FILTROM 0x10
#define DIR_OPT_FILTRBF 0x20
#define DIR_OPT_FILTXPS 0x40
//****************************************************************************** 

typedef enum {
    //static vals
    INFS_DEV_ID = 1,
    INFS_HW_VER,
    INFS_SERIAL_G,
    INFS_SERIAL_L,
    INFS_TS_ASM,
    INFS_TS_FW,
    INFS_TS_BOOT,
    INFS_FLA_SIZE,
    INFS_MAX_ROM_SIZE,
    INFS_TS_CIC,

    //dynamic vals
    INFD_BOOT_CTR = 128,
    INFD_GAME_CTR,
    INFD_RST_SRC,
    INFD_BOOT_MODE,
    INFD_PWR_SYS,
    INFD_PWR_USB,
    INFD_BAT_DRY,
    INFD_VCC_BAT,
    INFD_VCC_1V2,
    INFD_VCC_1V8,
    INFD_VCC_2V5,
    INFD_VCC_3V3,
    INFD_VCC_5V0,

} SysInfID;

typedef enum {
    DEV_BRM_OFF = 0x00,
    DEV_BRM_EEP4K,
    DEV_BRM_EEP16K,
    DEV_BRM_SRM32K,
    DEV_BRM_SRM96K,
    DEV_BRM_FLASH,
    DEV_BRM_SRM128K
} DevBramType;

typedef enum {
    DEV_PATH_GPAK,
    DEV_PATH_GDATA,
    DEV_PATH_BRM,
    DEV_PATH_APPF,
    DEV_PATH_DISK
} DevPathType;

typedef enum {
    DEV_RTCMODE_OFF,
    DEV_RTCMODE_STD, //can change system time
    DEV_RTCMODE_RDO //read only
} DevRtcMode;

typedef enum {
    DEV_ROM_OFF,
    DEV_ROM_MENU,
    DEV_ROM_GPAK,
    DEV_ROM_IPL,
    DEV_ROM_DDROM,
} DevRomType;

typedef struct {//do not use enum types!
    u32 brom_type; //   boot rom type
    u32 gpak_size; //   gpak rom size
    u32 brm_size; //    gpak backup tam size
    u32 brm_type; //    gpak bacup ram type
    u32 rtc_mode; //    DevRtcMode
    u32 dd_en; //       use dd addon
    u32 gpak_wren; //   gpak rom writable
    u32 gpak_key; //    key for encrypted roms
    u32 reserved[8];
} DevCfg;

typedef struct {
    u8 yar;
    u8 mon;
    u8 dom;
    u8 hur;
    u8 min;
    u8 sec;
    u8 dow;
    u8 reserved;
} RtcTime;

typedef struct {
    u8 han_brm;
    u8 han_disk;
    u8 han_rtc;
    u8 han_ddrom;
    u8 cache_brm;
    u8 cache_rtc;
    u8 reserved[10];
} HanStatus;
//****************************************************************************** 
#define ADDR_FCI_RAM    0x00000000
#define ADDR_FCI_SYS    0x10000000 //system registers
#define ADDR_FCI_DEV    0x10100000

#define ADDR_FCI_ROM    (ADDR_FCI_RAM + 0)
#define ADDR_FCI_IPL4   (ADDR_FCI_RAM + SIZE_RAM - 0x800000)
#define ADDR_FCI_MENU   (ADDR_FCI_RAM + SIZE_RAM - 0x100000)

#define ADDR_FCI_CFG    (ADDR_FCI_SYS + 0x00000) //system configl byte
#define ADDR_FCI_FIFO   (ADDR_FCI_SYS + 0x10000) //mcu fifo
#define ADDR_FCI_FAVB   (ADDR_FCI_SYS + 0x20000) //mcu fifo rd availalbe
#define ADDR_FCI_MBX    (ADDR_FCI_SYS + 0x30000) //mbx comm register

#define ADDR_FCI_GPAK   (ADDR_FCI_DEV + 0x20000)//cart regs

#define ADDR_PI_ROM     (KSEG1 | 0x10000000)
#define ADDR_PI_DDIPL   (KSEG1 | 0x06000000)
#define ADDR_PI_SRAM    (KSEG1 | 0x08000000)
#define ADDR_PI_SYM     (ADDR_PI_ROM + 0x3F80000)//dbg info
#define SIZE_RAM        0x10000000
//****************************************************************************** 
u32 max_ed(u32 v1, u32 v2);
u32 min_ed(u32 v1, u32 v2);
u8 ed_init_hw();
u32 ed_fifo_avb();
void ed_fifo_flush();
u32 ed_fifo_rda(void *dst, u32 len);
void ed_fifo_rd(void *dst, u32 len);
void ed_rx_string(u8 *string);
u32 ed_get_cart_id();
u8 ed_check_status();
u8 ed_cmd_nresp(u8 resp);

u8 ed_usb_wr_fci(u32 src, u32 len);
u8 ed_usb_wr(void *src, u32 len);
u8 ed_urt_wr(u8 *src, u32 len);
int ed_dbg_wr_urt(char *buf, unsigned int len);
int ed_dbg_wr_usb(char *buf, unsigned int len);
void ed_mbx_wr(u32 val);
u32 ed_mbx_rd();

u8 ed_fs_rx_next_rec(FileInfo *inf);
u8 ed_fs_init();
u8 ed_fs_file_open(u8 *path, u8 mode);
u8 ed_fs_file_close();
u32 ed_fs_file_available();
u8 ed_fs_file_read(void *dst, u32 len);
u8 ed_fs_file_read_fci(u32 addr, u32 len);
u8 ed_fs_file_write(void *src, u32 len);
u8 ed_fs_file_write_fci(u32 addr, u32 len);
u8 ed_fs_file_set_ptr(u32 addr);
u8 ed_fs_file_info(u8 *path, FileInfo *inf);
u8 ed_fs_file_del(u8 *path);
u8 ed_fs_file_crc(u32 len, u32 *crc_base);
u8 ed_fs_dir_make(u8 *path);
u8 ed_fs_dir_load(u8 *path, u8 dir_opt);
void ed_fs_dir_get_size(u16 *size);
void ed_fs_dir_seek_idx(u16 *idx);
void ed_fs_dir_get_recs(u16 start_idx, u16 amount, u16 max_name_len);
u8 ed_fs_file_copy(u8 *src, u8 *dst, u8 dst_mode);
u8 ed_fs_file_seek_pat(u8 *pat, u8 psize, u32 fsize, u32 *paddr);
u8 ed_fs_file_test(u8 *path);
u8 ed_fs_dir_test(u8 *path);

void ed_fci_set(u8 val, u32 addr, u32 len);
u8 ed_fci_test(u8 val, u32 addr, u32 len);
void ed_fci_rd(u32 addr, void *dst, u32 len);
void ed_fci_wr(u32 addr, void *src, u32 len);
void ed_fci_crc(u32 addr, u32 len, u32 *crc_base);

u32 ed_get_ticks();
void ed_sys_get_inf(u32 *list, u8 list_len);

u8 ed_dev_stop(u8 flush_fifo);
u8 ed_dev_start();
void ed_dev_game_ctr();
u8 ed_dev_set_path(u8 *path, DevPathType path_type);
u8 ed_dev_set_cfg(DevCfg *cfg);
void ed_dev_wr_swap(u8 swap_en);
u8 ed_dev_xps(u8 *path, u32 base_addr);
u8 ed_dev_get_path(u8 *path, DevPathType path_type);
u8 ed_dev_brm_rmap(u32 addr);
void ed_dev_han_stat(HanStatus *stat);

void ed_rtc_get(RtcTime *rtc);
void ed_rtc_set(RtcTime *rtc);
s32 ed_rtcc_curval();

u8 ed_sys_fpga_init(u32 len);
u8 ed_sys_efu_install(u8 *path);
u8 ed_sys_reset();

double ed_measure_fps();
#endif	/* EVERDRIVE_H */

