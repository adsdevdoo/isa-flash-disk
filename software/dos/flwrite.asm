; FLWRITE.COM - write a file to the flash, block by block, with verification.
; Usage: FLWRITE file [/D] [/O:block] [/Y] [/M:seg] [/P:port]
;   /D  the file is a hard disk image (disk format 3, docs/programming.md): it is cut into logical blocks of
;       127 sectors (65024 bytes), stored inverted; a changed block goes into the free flash block with a new
;       block header and its old copy becomes the free block, so a power failure never loses a block
;   /O  start at that block (hex): logical block with /D, 64 KB flash block without; for an image in parts
;   /Y  do not ask for confirmation
; Without /D the file is a raw flash image from address 0 (ROM, descriptor and disk), e.g. made by FLREAD.
; Needs the WRITE jumper JP1. At the end the resident option ROM is told to read the block map again.

        cpu     8086
        bits    16
        org     100h

%include "isaflash.inc"
%include "dosmacro.inc"

LBLK_BYTES      equ     SECTORS_PER_LBLK * SECTOR_SIZE  ; 65024

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

.mem:   test    byte [opt_flags], OPT_DISK
        jz      .open
        call    load_desc
        jnc     .desc
        mov     dx, msg_nodisk
        jmp     die
.desc:  call    scan_map
        jnc     .open
        mov     dx, msg_nomap
        jmp     die

.open:  mov     dx, fname
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

        ; blocks = ceil(size / block size); capacity from the first block on
        mov     ax, [size_lo]
        mov     dx, [size_hi]
        test    byte [opt_flags], OPT_DISK
        jz      .raw
        mov     cx, LBLK_BYTES
        cmp     dx, cx
        jae     .big
        div     cx
        or      dx, dx
        jz      .cnt
        inc     ax
        jmp     .cnt
.raw:   mov     ax, dx                  ; 64 KB blocks
        cmp     word [size_lo], 0
        je      .cnt
        inc     ax
.cnt:   or      ax, ax
        jnz     .nonempty
        mov     dx, msg_empty
        jmp     die
.nonempty:
        mov     [nblocks], ax
        mov     al, [d_nl]              ; /D: logical blocks
        test    byte [opt_flags], OPT_DISK
        jnz     .cap
        mov     al, [chips]
        mov     cl, 4
        shl     al, cl                  ; raw: 16 flash blocks per chip
.cap:   mov     dl, [opt_off]
        sub     al, dl
        jb      .big
        mov     [block], dl
        xor     ah, ah
        cmp     [nblocks], ax
        jbe     .fits
.big:   mov     dx, msg_toobig
        jmp     die
.fits:
        PRINT   msg_ask1
        mov     ax, [nblocks]
        call    print_dec
        mov     dx, msg_ask_raw
        test    byte [opt_flags], OPT_DISK
        jz      .ask2
        mov     dx, msg_ask_disk
.ask2:  call    print_dollar
        mov     al, [block]
        xor     ah, ah
        call    print_dec
        mov     dx, msg_ask3
        call    ask_yes
        je      .go
        mov     dx, msg_cancel
        jmp     die

.go:    call    vpp_test
        test    al, SR_VPP_LOW
        jz      .blk
        mov     dx, msg_jumper
        jmp     die

.blk:   ; buffer: raw = FFh then up to 64 KB of the file; disk = 00h, 65024 bytes, then all inverted, so the
        ; part after the file and the header area become FFh
        push    es
        mov     es, [bufseg]
        xor     di, di
        mov     ax, 0FFFFh
        mov     cx, 8000h
        test    byte [opt_flags], OPT_DISK
        jz      .fill
        xor     ax, ax
.fill:  rep     stosw
        pop     es
        push    ds
        mov     bx, [handle]
        xor     dx, dx
        mov     cx, LBLK_BYTES
        test    byte [cs:opt_flags], OPT_DISK
        mov     ds, [cs:bufseg]
        jnz     .rd2
        mov     cx, 8000h
        mov     ah, 3Fh
        int     21h
        jc      .rerr
        cmp     ax, 8000h
        jb      .readok
        mov     dx, 8000h
        mov     cx, 8000h
.rd2:   mov     ah, 3Fh
        int     21h
        jc      .rerr
.readok:
        pop     ds
        test    byte [opt_flags], OPT_DISK
        jnz     .disk
        jmp     .rawblk

.disk:  push    ds
        push    es
        mov     ax, [bufseg]
        mov     ds, ax
        mov     es, ax
        xor     si, si
        xor     di, di
        mov     cx, 8000h
.inv:   lodsw
        not     ax                      ; stored byte = NOT data
        stosw
        loop    .inv
        pop     es
        pop     ds
        PRINT   msg_block
        mov     al, [block]
        xor     ah, ah
        call    print_dec
        PRINT   msg_colon
        mov     bl, [block]
        call    cmp_lblock
        jc      .changed
        PRINT   msg_same
        jmp     .advance
.changed:
        mov     al, [block]
        call    buf_header
        mov     bl, [fl_free]
        PRINT   msg_into
        mov     al, bl
        xor     ah, ah
        call    print_dec
        PRINT   msg_comma
        call    write_block
        jc      .werr
        xor     bh, bh                  ; the new copy is complete: it becomes the block, the old one is free
        mov     bl, [block]
        mov     al, [fmap + bx]
        mov     ah, [fl_free]
        mov     [fmap + bx], ah
        mov     [fl_free], al
        call    say_action
        jmp     .advance

.rawblk:
        PRINT   msg_block
        mov     al, [block]
        xor     ah, ah
        call    print_dec
        PRINT   msg_colon
        mov     bl, [block]
        call    write_block
        jc      .werr
        call    say_action

.advance:
        inc     byte [block]
        dec     word [nblocks]
        jz      .end
        jmp     .blk
.end:   call    vpp_off
        call    card_safe
        call    remount
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
        call    card_safe
        call    remount
        mov     dx, msg_failend
        jmp     die

usage:  PRINT   msg_usage
        mov     al, 2
        mov     ah, 4Ch
        int     21h

say_action:
        mov     dx, msg_same
        cmp     byte [wb_action], 0
        je      .say
        mov     dx, msg_prog
        cmp     byte [wb_action], 1
        je      .say
        mov     dx, msg_erprog
.say:   jmp     print_dollar

; cmp_lblock: BL = logical block -> CF = its 127 data sectors differ from the buffer
cmp_lblock:
        push    ax
        push    bx
        push    cx
        push    si
        push    di
        push    es
        xor     bh, bh
        mov     ah, [fmap + bx]
        mov     cl, 3
        shl     ah, cl                  ; first bank of the physical block
        mov     es, [bufseg]
        xor     di, di
        xor     bl, bl
.bank:  mov     al, ah
        add     al, bl
        call    set_bank
        mov     cx, WINDOW_SIZE
        cmp     bl, HDR_BANK
        jne     .full
        mov     cx, HDR_WOFF            ; the header sector is not data
.full:  push    ds
        mov     ds, [winseg]
        xor     si, si
        repe    cmpsb
        pop     ds
        jne     .diff
        inc     bl
        cmp     bl, BANKS_PER_BLOCK
        jb      .bank
        xor     al, al
        call    set_bank
        clc
        jmp     .out
.diff:  xor     al, al
        call    set_bank
        stc
.out:   pop     es
        pop     di
        pop     si
        pop     cx
        pop     bx
        pop     ax
        ret

%include "doslib.inc"
%include "flashlib.inc"

handle          dw      0
size_lo         dw      0
size_hi         dw      0
nblocks         dw      0
block           db      0
msg_banner:     db      'FLWRITE 1.2 - ISA Flash Disk', 13, 10, '$'
msg_usage:      db      'Usage: FLWRITE file [/D] [/O:block] [/Y] [/M:seg] [/P:port]', 13, 10
                db      '  /D  hard disk image (disk format 3)', 13, 10
                db      '  /O  start at that block (hex), for split images', 13, 10
                db      '  /Y  no confirmation', 13, 10, '$'
msg_nomem:      db      'Not enough memory (needs 128 KB).', 13, 10, '$'
msg_nodisk:     db      'No format 3 disk on the card: run FLFORMAT /E first.', 13, 10, '$'
msg_nomap:      db      'Disk block map damaged: run FLFORMAT /E first.', 13, 10, '$'
msg_open:       db      'Cannot open the file.', 13, 10, '$'
msg_empty:      db      'The file is empty.', 13, 10, '$'
msg_toobig:     db      'The file does not fit.', 13, 10, '$'
msg_ask1:       db      'Write $'
msg_ask_raw:    db      ' flash block(s) of 64 KB from block $'
msg_ask_disk:   db      ' disk block(s) of 127 sectors from block $'
msg_ask3:       db      '? (Y/N) $'
msg_cancel:     db      'Cancelled.', 13, 10, '$'
msg_block:      db      'Block $'
msg_colon:      db      ': $'
msg_into:       db      'to flash block $'
msg_comma:      db      ', $'
msg_same:       db      'unchanged', 13, 10, '$'
msg_prog:       db      'programmed, verified', 13, 10, '$'
msg_erprog:     db      'erased, programmed, verified', 13, 10, '$'
msg_read:       db      'File read error.', 13, 10, '$'
msg_fail:       db      'FAILED, status $'
msg_failend:    db      'h. Blocks before this one are written.', 13, 10, '$'
msg_done:       db      'Done. Restart the computer if DOS used the flash disk before.', 13, 10, '$'

        section .bss
fname:          resb    128
tmpbuf:         resb    WINDOW_SIZE
