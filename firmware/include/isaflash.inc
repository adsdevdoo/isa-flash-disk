; ISA Flash Disk - definitions shared by the option ROM and the DOS utilities.
; Hardware: docs/architecture.md, docs/memory-map.md. Flash commands: Intel 28F008SA datasheet 290429-008, table 3.

%ifndef ISAFLASH_INC
%define ISAFLASH_INC

; ---- Card registers (write only), relative to the I/O base selected with SW2 ----
REG_BANK        equ 0           ; bits 6..0 = flash A19..A13, bit 7 = chip (0 = U1, 1 = U2)
REG_CTRL        equ 1           ; bit 0 = WE_EN, bit 1 = VPP_EN
CTRL_WE_EN      equ 01h
CTRL_VPP_EN     equ 02h

DEFAULT_PORT    equ 2A0h
DEFAULT_WINDOW  equ 0CC00h      ; segment of the 8 KB window (SW1 default)
WINDOW_SIZE     equ 2000h       ; 8 KB
WINDOW_FIRST    equ 0C800h      ; option ROM scan range, XT Technical Reference 5-10
WINDOW_LAST     equ 0F400h

; ---- Flash layout (linear addresses on the card) ----
SECTOR_SIZE     equ 512
SECTORS_PER_BANK equ WINDOW_SIZE / SECTOR_SIZE  ; 16, so BANK register = linear sector >> 4
ROM_SIZE        equ 2000h       ; option ROM: linear 000000h..001FFFh = bank 0
DESC_LINEAR     equ 2000h       ; disk descriptor: bank 1, offset 0
DATA_LINEAR     equ 10000h      ; disk data: from erase block 1
DATA_FIRST_SECTOR equ DATA_LINEAR / SECTOR_SIZE ; 128
CHIP_SIZE_KB    equ 1024
BLOCK_SIZE      equ 10000h      ; 64 KB erase block
BANKS_PER_BLOCK equ BLOCK_SIZE / WINDOW_SIZE    ; 8

; ---- Option ROM header (offsets inside the ROM image) ----
ROMH_SIG        equ 08h         ; 'ISAFLASH'
ROMH_PORT       equ 10h         ; dw I/O base, patched by FLFORMAT
ROMH_VERSION    equ 12h         ; db major, db minor
ROM_SIGNATURE   equ 'ISAFLASH'

; ---- Disk descriptor (512 bytes at DESC_LINEAR) ----
DESC_SIG        equ 00h         ; 'ISAFLDSK'
DESC_VERSION    equ 08h         ; dw 1
DESC_CHIPS      equ 0Ah         ; db 1 or 2
DESC_CYLS       equ 0Ch         ; dw
DESC_HEADS      equ 0Eh         ; dw
DESC_SPT        equ 10h         ; dw
DESC_TOTAL      equ 12h         ; dw total data sectors (<= 3968)
DESC_DATA       equ 14h         ; dw first data sector (linear sector number, 128)
DESC_CHECKSUM   equ 1FFh        ; byte: all 512 bytes sum to 0 (mod 256)
DESC_SIGNATURE  equ 'ISAFLDSK'
DISK_HEADS      equ 4
DISK_SPT        equ 16

; ---- 28F008SA (datasheet table 3, table 4) ----
FL_READ_ARRAY   equ 0FFh
FL_READ_ID      equ 90h
FL_READ_STATUS  equ 70h
FL_CLEAR_STATUS equ 50h
FL_ERASE_SETUP  equ 20h
FL_CONFIRM      equ 0D0h
FL_PROGRAM      equ 40h
FL_MFR_INTEL    equ 89h
FL_DEV_28F008SA equ 0A2h
SR_READY        equ 80h         ; SR.7 WSMS
SR_ERASE_ERR    equ 20h         ; SR.5
SR_PROG_ERR     equ 10h         ; SR.4
SR_VPP_LOW      equ 08h         ; SR.3

%endif
