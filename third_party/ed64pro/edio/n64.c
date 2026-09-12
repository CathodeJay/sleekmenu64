
#include "appmain.h"


void pi_rd_safe(void *ram, unsigned long pi_address, unsigned long len) {

    u8 buff[8192]__attribute__((aligned(8)));
    u32 block;

    while (len) {

        block = sizeof (buff);
        if (block > len)block = len;
        if (block % 4 != 0) {
            pi_rd(buff, pi_address, block + (4 - block % 4));
        } else {
            pi_rd(buff, pi_address, block);
        }
        memcpy(ram, buff, block);

        len -= block;
        pi_address += block;
        ram += block;
    }
}

void pi_rd(void *dst, unsigned long pi_address, unsigned long len) {

    if ((u32) dst % 8 != 0 || len % 4 != 0) {
        pi_rd_safe(dst, pi_address, len);
        return;
    }

    pi_address &= 0x1FFFFFFF;
    data_cache_hit_writeback_invalidate(dst, len);
    //dma_read(dst, pi_address, len);
    dma_read_raw_async(dst, pi_address, len);
    dma_wait();
}

void pi_wr_safe(void *ram, unsigned long pi_address, unsigned long len) {

    u8 buff[8192]__attribute__((aligned(8)));
    u32 block;

    while (len) {

        block = sizeof (buff);
        if (block > len)block = len;

        memcpy(buff, ram, block);
        pi_wr(buff, pi_address, block);

        len -= block;
        pi_address += block;
        ram += block;
    }
}

void pi_wr(void *src, unsigned long pi_address, unsigned long len) {

    if ((u32) src % 8 != 0) {
        pi_wr_safe(src, pi_address, len);
        return;
    }

    pi_address &= 0x1FFFFFFF;
    data_cache_hit_writeback(src, len);
    //dma_write(src, pi_address, len);
    dma_write_raw_async(src, pi_address, len);
    dma_wait();
}
