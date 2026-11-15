; FLWRITE.COM - write a file to the flash, block by block, with verification.
; Usage: FLWRITE file [/D] [/O:block] [/Y] [/M:seg] [/P:port]
;   /O  start at that 64 KB block of the area (hex), for an image written in parts
;   /D  the file is a hard disk image: written from 64 KB on, the ROM and descriptor block stays as it is;
;       stored inverted (disk format 2) and never into the spare block (the last one)
;   /Y  do not ask for confirmation
; Without /D the file is a whole flash image from address 0 (ROM, descriptor and disk).
; Needs the WRITE jumper JP1. Identical 64 KB blocks are skipped; a block is erased only when a bit must
; change from 0 to 1.

        cpu     8086
        bits    16
        org     100h

%include "isaflash.inc"
%include "dosmacro.inc"

start:  cld
        mov     byte [fname], 0
        call    parse_args
        jc      usage
        cmp     byte [fname], 0
        je      usage
        PRINT   msg_banner
        call    install_break
        call    card_find
        jnc     .found
        jmp     not_found
.found: call    print_card
        call    alloc_buffer
        jnc     .mem
        mov     dx, msg_nomem
        jmp     die

.mem:   mov     dx, fname
        mov     ax, 3D00h
        int     21h
        jnc     .opened
        mov     dx, msg_open
        jmp     die
.opened:
        mov     [handle], ax
        mov     bx, ax
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4202h               ; size = seek to the end
        int     21h
        mov     [size_lo], ax
        mov     [size_hi], dx
        mov     bx, [handle]
        xor     cx, cx
        xor     dx, dx
        mov     ax, 4200h
        int     21h

        ; blocks = ceil(size / 64 KB)
        mov     ax, [size_hi]
        cmp     word [size_lo], 0
        je      .exact
        inc     ax
.exact: or      ax, ax
        jnz     .nonempty
        mov     dx, msg_empty
        jmp     die
.nonempty:
        mov     [nblocks], ax
        xor     bl, bl                  ; first block
        mov     al, [chips]
        mov     cl, 4
        shl     al, cl                  ; 16 blocks per chip
        test    byte [opt_flags], OPT_DISK
        jz      .whole
        mov     bl, DATA_LINEAR / BLOCK_SIZE
        sub     al, 2                   ; block 0 and the spare block
.whole: mov     dl, [opt_off]          ; /O: start that many blocks further
        add     bl, dl
        sub     al, dl
        jb      .big
        mov     [first], bl
        xor     ah, ah
        cmp     [nblocks], ax
        jbe     .fits
.big:   mov     dx, msg_toobig
        jmp     die
.fits:
        PRINT   msg_ask1
        mov     ax, [nblocks]
        mov     cl, 6
        shl     ax, cl
        call    print_dec
        PRINT   msg_ask2
        mov     al, [first]
        xor     ah, ah
        mov     cl, 6
        shl     ax, cl
        call    print_dec
        mov     dx, msg_ask3
        call    ask_yes
        je      .go
        mov     dx, msg_cancel
        jmp     die

.go:    call    vpp_test
        test    al, SR_VPP_LOW
        jz      .vpp
        mov     dx, msg_jumper
        jmp     die
.vpp:   mov     al, [first]
        mov     [block], al

.blk:   ; buffer = FFh (disk image: 00h, inverted below), then up to 64 KB from the file
        push    es
        mov     es, [bufseg]
        xor     di, di
        mov     ax, 0FFFFh
        test    byte [opt_flags], OPT_DISK
        jz      .fill
        xor     ax, ax
.fill:  mov     cx, 8000h
        rep     stosw
        pop     es
        push    ds
        mov     bx, [handle]
        mov     ds, [bufseg]
        xor     dx, dx
        mov     cx, 8000h
        mov     ah, 3Fh
        int     21h
        jc      .rerr
        cmp     ax, 8000h
        jb      .readok
        mov     dx, 8000h
        mov     cx, 8000h
        mov     ah, 3Fh
        int     21h
        jc      .rerr
.readok:
        pop     ds
        test    byte [opt_flags], OPT_DISK
        jz      .stored
        push    ds
        push    es
        mov     ax, [bufseg]
        mov     ds, ax
        mov     es, ax
        xor     si, si
        xor     di, di
        mov     cx, 8000h
.inv:   lodsw
        not     ax                      ; disk format 2: stored byte = NOT data
        stosw
        loop    .inv
        pop     es
        pop     ds
.stored:

        PRINT   msg_block
        mov     al, [block]
        xor     ah, ah
        call    print_dec
        PRINT   msg_colon
        mov     bl, [block]
        call    write_block
        jc      .werr
        mov     dx, msg_same
        cmp     byte [wb_action], 0
        je      .say
        mov     dx, msg_prog
        cmp     byte [wb_action], 1
        je      .say
        mov     dx, msg_erprog
.say:   call    print_dollar

        inc     byte [block]
        dec     word [nblocks]
        jnz     .blk

        call    vpp_off
        mov     bx, [handle]
        mov     ah, 3Eh
        int     21h
        PRINT   msg_done
        xor     al, al
        jmp     exit_prog

.rerr:  pop     ds
        mov     dx, msg_read
        jmp     die
.werr:  push    ax
        PRINT   msg_fail
        pop     ax
        call    print_hex8
        mov     dx, msg_failend
        jmp     die

usage:  PRINT   msg_usage
        mov     al, 2
        mov     ah, 4Ch
        int     21h

%include "doslib.inc"
%include "flashlib.inc"

handle          dw      0
size_lo         dw      0
size_hi         dw      0
nblocks         dw      0
first           db      0
block           db      0
msg_banner:     db      'FLWRITE 1.1 - ISA Flash Disk', 13, 10, '$'
msg_usage:      db      'Usage: FLWRITE file [/D] [/O:block] [/Y] [/M:seg] [/P:port]', 13, 10
                db      '  /D  hard disk image, written from 64 KB on', 13, 10
                db      '  /O  start at that 64 KB block (hex), for split images', 13, 10
                db      '  /Y  no confirmation', 13, 10, '$'
msg_nomem:      db      'Not enough memory (needs 128 KB).', 13, 10, '$'
msg_open:       db      'Cannot open the file.', 13, 10, '$'
msg_empty:      db      'The file is empty.', 13, 10, '$'
msg_toobig:     db      'The file does not fit into the flash.', 13, 10, '$'
msg_ask1:       db      'Write $'
msg_ask2:       db      ' KB at flash offset $'
msg_ask3:       db      ' KB? (Y/N) $'
msg_cancel:     db      'Cancelled.', 13, 10, '$'
msg_block:      db      'Block $'
msg_colon:      db      ': $'
msg_same:       db      'unchanged', 13, 10, '$'
msg_prog:       db      'programmed, verified', 13, 10, '$'
msg_erprog:     db      'erased, programmed, verified', 13, 10, '$'
msg_read:       db      'File read error.', 13, 10, '$'
msg_fail:       db      'FAILED, status $'
msg_failend:    db      'h. Flash left as is up to this block.', 13, 10, '$'
msg_done:       db      'Done.', 13, 10, '$'

        section .bss
fname:          resb    128
tmpbuf:         resb    WINDOW_SIZE
