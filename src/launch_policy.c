/* SPDX-License-Identifier: AGPL-3.0-only */
#include "launch.h"
#include <stdio.h>
#include <string.h>
#include <strings.h>

bool launch_resolve_paths(const char *path, sm_launch_paths_t *paths) {
    const char *relative;
    int written;
    if (!paths) return false;
    memset(paths, 0, sizeof(*paths));
    if (!path || !path[0]) return false;

    /* Catalog paths are relative to the card root, which is also what the
     * card scan records; a leading slash and an sd:/ prefix say so
     * explicitly. A bare relative path is tried at the root first and then
     * under ROMS/, which is where a catalog built against a ROMS folder
     * rather than the card (make metadata without CARD) would put it. */
    if (!strncasecmp(path, "sd:/", 4)) {
        written = snprintf(paths->primary, sizeof(paths->primary), "sd:/%s", path + 4);
        if (written < 0 || written >= (int)sizeof(paths->primary)) return false;
        paths->count = 1;
        return true;
    }
    relative = path[0] == '/' ? path + 1 : path;
    if (!relative[0]) return false;
    written = snprintf(paths->primary, sizeof(paths->primary), "sd:/%s", relative);
    if (written < 0 || written >= (int)sizeof(paths->primary)) return false;
    paths->count = 1;
    if (path[0] == '/' || !strncasecmp(relative, "ROMS/", 5)) return true;

    written = snprintf(paths->fallback, sizeof(paths->fallback), "sd:/ROMS/%s", relative);
    if (written < 0 || written >= (int)sizeof(paths->fallback)) {
        memset(paths, 0, sizeof(*paths));
        return false;
    }
    paths->count = 2;
    return true;
}

sm_rom_format_t sm_rom_format_detect(const uint8_t *header, size_t length) {
    if (!header || length < 4u) return SM_ROM_FORMAT_UNKNOWN;
    if (header[0]==0x80u && header[1]==0x37u && header[2]==0x12u && header[3]==0x40u)
        return SM_ROM_FORMAT_Z64;
    if (header[0]==0x37u && header[1]==0x80u && header[2]==0x40u && header[3]==0x12u)
        return SM_ROM_FORMAT_V64;
    if (header[0]==0x40u && header[1]==0x12u && header[2]==0x37u && header[3]==0x80u)
        return SM_ROM_FORMAT_N64;
    return SM_ROM_FORMAT_UNKNOWN;
}

const char *sm_rom_format_name(sm_rom_format_t format) {
    switch (format) {
        case SM_ROM_FORMAT_Z64: return "z64";
        case SM_ROM_FORMAT_V64: return "v64";
        case SM_ROM_FORMAT_N64: return "n64";
        default: return "?";
    }
}

void sm_rom_header_normalise(uint8_t *header, size_t length, sm_rom_format_t format) {
    size_t i;
    if (!header) return;
    if (format == SM_ROM_FORMAT_V64) {
        for (i = 0; i + 1u < length; i += 2u) {
            uint8_t t = header[i]; header[i] = header[i + 1u]; header[i + 1u] = t;
        }
    } else if (format == SM_ROM_FORMAT_N64) {
        for (i = 0; i + 3u < length; i += 4u) {
            uint8_t a = header[i], b = header[i + 1u];
            header[i] = header[i + 3u]; header[i + 1u] = header[i + 2u];
            header[i + 2u] = b; header[i + 3u] = a;
        }
    }
}

bool launch_suffix_is_rom(const char *path) {
    size_t n = path ? strlen(path) : 0;
    if (n < 4u) return false;
    return !strcasecmp(path + n - 4, ".z64") || !strcasecmp(path + n - 4, ".v64") ||
           !strcasecmp(path + n - 4, ".n64");
}

bool launch_suffix_is_disk(const char *path) {
    size_t n = path ? strlen(path) : 0;
    return n >= 4u && !strcasecmp(path + n - 4, ".ndd");
}

sm_disk_region_t launch_disk_region(const uint8_t *head, size_t length) {
    if (!head || length < SM_DISK_HEAD_SIZE) return SM_DISK_REGION_UNKNOWN;
    if (head[0] == 0xE8 && head[1] == 0x48 && head[2] == 0xD3 && head[3] == 0x16) return SM_DISK_REGION_JAPAN;
    if (head[0] == 0x22 && head[1] == 0x63 && head[2] == 0xEE && head[3] == 0x56) return SM_DISK_REGION_USA;
    return SM_DISK_REGION_DEVELOPMENT;
}

const char *launch_disk_region_name(sm_disk_region_t region) {
    switch (region) {
        case SM_DISK_REGION_JAPAN: return "JPN";
        case SM_DISK_REGION_USA: return "USA";
        case SM_DISK_REGION_DEVELOPMENT: return "DEV";
        default: return "?";
    }
}

const char *launch_disk_ipl_name(sm_disk_region_t region) {
    switch (region) {
        case SM_DISK_REGION_JAPAN: return "NDDJ2.n64";
        case SM_DISK_REGION_USA: return "NDDE0.n64";
        case SM_DISK_REGION_DEVELOPMENT: return "NDXJ0.n64";
        default: return NULL;
    }
}


/* Reflected CRC-32, polynomial 0xEDB88320 — the same function the bit-by-bit
   version computed, table-driven. The bitwise form cost roughly 50 cycles per
   byte, which is about 36 seconds for a 64 MiB read-back on a 93 MHz VR4300;
   this is closer to 6. launch_policy_test.c forges an IPL3 whose CRC must hit
   an exact target, so any deviation from the original fails immediately. */
static const uint32_t CRC32_TABLE[256] = {
    0x00000000u, 0x77073096u, 0xEE0E612Cu, 0x990951BAu,
    0x076DC419u, 0x706AF48Fu, 0xE963A535u, 0x9E6495A3u,
    0x0EDB8832u, 0x79DCB8A4u, 0xE0D5E91Eu, 0x97D2D988u,
    0x09B64C2Bu, 0x7EB17CBDu, 0xE7B82D07u, 0x90BF1D91u,
    0x1DB71064u, 0x6AB020F2u, 0xF3B97148u, 0x84BE41DEu,
    0x1ADAD47Du, 0x6DDDE4EBu, 0xF4D4B551u, 0x83D385C7u,
    0x136C9856u, 0x646BA8C0u, 0xFD62F97Au, 0x8A65C9ECu,
    0x14015C4Fu, 0x63066CD9u, 0xFA0F3D63u, 0x8D080DF5u,
    0x3B6E20C8u, 0x4C69105Eu, 0xD56041E4u, 0xA2677172u,
    0x3C03E4D1u, 0x4B04D447u, 0xD20D85FDu, 0xA50AB56Bu,
    0x35B5A8FAu, 0x42B2986Cu, 0xDBBBC9D6u, 0xACBCF940u,
    0x32D86CE3u, 0x45DF5C75u, 0xDCD60DCFu, 0xABD13D59u,
    0x26D930ACu, 0x51DE003Au, 0xC8D75180u, 0xBFD06116u,
    0x21B4F4B5u, 0x56B3C423u, 0xCFBA9599u, 0xB8BDA50Fu,
    0x2802B89Eu, 0x5F058808u, 0xC60CD9B2u, 0xB10BE924u,
    0x2F6F7C87u, 0x58684C11u, 0xC1611DABu, 0xB6662D3Du,
    0x76DC4190u, 0x01DB7106u, 0x98D220BCu, 0xEFD5102Au,
    0x71B18589u, 0x06B6B51Fu, 0x9FBFE4A5u, 0xE8B8D433u,
    0x7807C9A2u, 0x0F00F934u, 0x9609A88Eu, 0xE10E9818u,
    0x7F6A0DBBu, 0x086D3D2Du, 0x91646C97u, 0xE6635C01u,
    0x6B6B51F4u, 0x1C6C6162u, 0x856530D8u, 0xF262004Eu,
    0x6C0695EDu, 0x1B01A57Bu, 0x8208F4C1u, 0xF50FC457u,
    0x65B0D9C6u, 0x12B7E950u, 0x8BBEB8EAu, 0xFCB9887Cu,
    0x62DD1DDFu, 0x15DA2D49u, 0x8CD37CF3u, 0xFBD44C65u,
    0x4DB26158u, 0x3AB551CEu, 0xA3BC0074u, 0xD4BB30E2u,
    0x4ADFA541u, 0x3DD895D7u, 0xA4D1C46Du, 0xD3D6F4FBu,
    0x4369E96Au, 0x346ED9FCu, 0xAD678846u, 0xDA60B8D0u,
    0x44042D73u, 0x33031DE5u, 0xAA0A4C5Fu, 0xDD0D7CC9u,
    0x5005713Cu, 0x270241AAu, 0xBE0B1010u, 0xC90C2086u,
    0x5768B525u, 0x206F85B3u, 0xB966D409u, 0xCE61E49Fu,
    0x5EDEF90Eu, 0x29D9C998u, 0xB0D09822u, 0xC7D7A8B4u,
    0x59B33D17u, 0x2EB40D81u, 0xB7BD5C3Bu, 0xC0BA6CADu,
    0xEDB88320u, 0x9ABFB3B6u, 0x03B6E20Cu, 0x74B1D29Au,
    0xEAD54739u, 0x9DD277AFu, 0x04DB2615u, 0x73DC1683u,
    0xE3630B12u, 0x94643B84u, 0x0D6D6A3Eu, 0x7A6A5AA8u,
    0xE40ECF0Bu, 0x9309FF9Du, 0x0A00AE27u, 0x7D079EB1u,
    0xF00F9344u, 0x8708A3D2u, 0x1E01F268u, 0x6906C2FEu,
    0xF762575Du, 0x806567CBu, 0x196C3671u, 0x6E6B06E7u,
    0xFED41B76u, 0x89D32BE0u, 0x10DA7A5Au, 0x67DD4ACCu,
    0xF9B9DF6Fu, 0x8EBEEFF9u, 0x17B7BE43u, 0x60B08ED5u,
    0xD6D6A3E8u, 0xA1D1937Eu, 0x38D8C2C4u, 0x4FDFF252u,
    0xD1BB67F1u, 0xA6BC5767u, 0x3FB506DDu, 0x48B2364Bu,
    0xD80D2BDAu, 0xAF0A1B4Cu, 0x36034AF6u, 0x41047A60u,
    0xDF60EFC3u, 0xA867DF55u, 0x316E8EEFu, 0x4669BE79u,
    0xCB61B38Cu, 0xBC66831Au, 0x256FD2A0u, 0x5268E236u,
    0xCC0C7795u, 0xBB0B4703u, 0x220216B9u, 0x5505262Fu,
    0xC5BA3BBEu, 0xB2BD0B28u, 0x2BB45A92u, 0x5CB36A04u,
    0xC2D7FFA7u, 0xB5D0CF31u, 0x2CD99E8Bu, 0x5BDEAE1Du,
    0x9B64C2B0u, 0xEC63F226u, 0x756AA39Cu, 0x026D930Au,
    0x9C0906A9u, 0xEB0E363Fu, 0x72076785u, 0x05005713u,
    0x95BF4A82u, 0xE2B87A14u, 0x7BB12BAEu, 0x0CB61B38u,
    0x92D28E9Bu, 0xE5D5BE0Du, 0x7CDCEFB7u, 0x0BDBDF21u,
    0x86D3D2D4u, 0xF1D4E242u, 0x68DDB3F8u, 0x1FDA836Eu,
    0x81BE16CDu, 0xF6B9265Bu, 0x6FB077E1u, 0x18B74777u,
    0x88085AE6u, 0xFF0F6A70u, 0x66063BCAu, 0x11010B5Cu,
    0x8F659EFFu, 0xF862AE69u, 0x616BFFD3u, 0x166CCF45u,
    0xA00AE278u, 0xD70DD2EEu, 0x4E048354u, 0x3903B3C2u,
    0xA7672661u, 0xD06016F7u, 0x4969474Du, 0x3E6E77DBu,
    0xAED16A4Au, 0xD9D65ADCu, 0x40DF0B66u, 0x37D83BF0u,
    0xA9BCAE53u, 0xDEBB9EC5u, 0x47B2CF7Fu, 0x30B5FFE9u,
    0xBDBDF21Cu, 0xCABAC28Au, 0x53B39330u, 0x24B4A3A6u,
    0xBAD03605u, 0xCDD70693u, 0x54DE5729u, 0x23D967BFu,
    0xB3667A2Eu, 0xC4614AB8u, 0x5D681B02u, 0x2A6F2B94u,
    0xB40BBE37u, 0xC30C8EA1u, 0x5A05DF1Bu, 0x2D02EF8Du,
};

uint32_t launch_crc32_update(uint32_t crc, const void *data, size_t length) {
    const uint8_t *p = data;
    while (length--) crc = CRC32_TABLE[(crc ^ *p++) & 0xFFu] ^ (crc >> 8);
    return crc;
}

uint32_t launch_crc32(const void *data, size_t length) {
    return ~launch_crc32_update(0xFFFFFFFFu, data, length);
}

sm_cic_t launch_cic_from_crc(uint32_t boot_crc) {
    switch (boot_crc) {
        case 0x6170A4A1u: return SM_CIC_6101;
        case 0x90BB6CB5u: return SM_CIC_6102;
        case 0x0B050EE0u: return SM_CIC_6103;
        case 0x98BC2C86u: return SM_CIC_6105;
        case 0xACC8580Au: return SM_CIC_6106;
        default: return SM_CIC_UNKNOWN;
    }
}

sm_launch_result_t launch_validate(const char *path, uint64_t size, uint64_t max_bytes, const uint8_t header[SM_N64_HEADER_SIZE], uint32_t *boot_crc, sm_cic_t *cic) {
    if (boot_crc) *boot_crc = 0;
    if (cic) *cic = SM_CIC_UNKNOWN;
    /* The extension is a hint, not evidence: the library carries byteswapped
       dumps named .z64 and native dumps named .n64. The header decides, and
       launch_prepare() has already normalised it into z64 order. */
    if (!launch_suffix_is_rom(path)) return SM_LAUNCH_BAD_SUFFIX;
    /* The ceiling is the cartridge's, not a constant: 64 MB of SDRAM on the
       X7, 126 MB on the Pro once it has been asked. */
    if (size < SM_N64_HEADER_SIZE || size > max_bytes || (size & 1u)) return SM_LAUNCH_BAD_SIZE;
    if (!header || header[0] != 0x80 || header[1] != 0x37 || header[2] != 0x12 || header[3] != 0x40) return SM_LAUNCH_BAD_MAGIC;
    uint32_t crc = launch_crc32(header + 0x40, 0xFC0);
    sm_cic_t detected = launch_cic_from_crc(crc);
    if (boot_crc) *boot_crc = crc;
    if (cic) *cic = detected;
    /* This five-entry table is for display only. The seed that actually gets
       handed to IPL3 is fingerprinted from the target ROM's own IPL3 at boot
       time, which covers every documented CIC and needs no database — so a
       miss here is worth showing and not worth blocking a launch over. */
    return SM_LAUNCH_OK;
}

/* These are what the user reads when a launch is refused, so each says what is
   wrong and, where there is one, what to do about it. Every one of them used to
   end in "launch preview: saves disabled", from when saves were unimplemented;
   they are implemented now and the warning was a lie. */
const char *launch_result_message(sm_launch_result_t result) {
    switch (result) {
        case SM_LAUNCH_OK: return "Ready";
        case SM_LAUNCH_BAD_SUFFIX: return "Not a ROM; .z64 or .v64 expected";
        case SM_LAUNCH_WORD_SWAPPED: return ".n64 word order cannot be swapped by the cartridge; convert to .z64";
        case SM_LAUNCH_BAD_SIZE: return "Invalid size; 4 KiB to the cartridge's limit, even";
        case SM_LAUNCH_BAD_MAGIC: return "Invalid z64 header magic; blocked";
        case SM_LAUNCH_WRONG_CARTRIDGE: return "No EverDrive-64 X7 or Pro found";
        case SM_LAUNCH_VERIFY_FAILED: return "CARTRIDGE VERIFY FAILED; blocked";
        case SM_LAUNCH_NO_64DD: return "64DD disks need an EverDrive-64 Pro";
        case SM_LAUNCH_NO_IPL: return "64DD IPL missing from ED64/64ddipl";
        case SM_LAUNCH_BAD_CHECKSUM: return "Bad checksum, unfixable here; Start again to try";
        default: return "ROM OPEN FAILED; read/transfer blocked";
    }
}
