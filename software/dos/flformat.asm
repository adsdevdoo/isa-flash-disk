; FLFORMAT.COM - install the option ROM and the disk descriptor into flash block 0.
; Usage: FLFORMAT romfile [/E [/T]] [/Y] [/M:seg] [/P:port]
;   romfile  FLASHROM.BIN (8192 bytes); the card's I/O port is written into it and the checksum fixed
;   /E       also erase and test every disk block (erase time, all FFh) and write an empty disk: block headers
;            for the logical blocks in the good flash blocks; blocks that fail or erase slower than 10 s are
;            marked bad in the descriptor and never used
;   /T       with /E: the full block test of FLTEST (also programs 00h into every byte and verifies)
;   /Y       do not ask for confirmation
; Disk format 3 (docs/programming.md): logical blocks of 127 sectors, one good flash block more than logical
; blocks (the number of logical blocks is kept even). Geometry 127 cylinders x 2 heads x (logical blocks / 2):
; 1 chip = 127/2/7 (1778 sectors), 2 chips = 127/2/15 (3810 sectors) when no block is bad.
; Without /E the disk and its bad block list stay. A disk of an older format must be erased (/E) and written again.
; Needs the WRITE jumper JP1.

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

.mem:   ; ROM file -> rombuf, must be exactly 8192 bytes with 55AA and 'ISAFLASH'
        mov     dx, fname
        mov     ax, 3D00h
        int     21h
        jnc     .opened
        mov     dx, msg_open
        jmp     die
.opened:
        mov     bx, ax
        mov     dx, rombuf
        mov     cx, ROM_SIZE + 1
        mov     ah, 3Fh
        int     21h
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        popf
        jc      .badrom
        cmp     ax, ROM_SIZE
        jne     .badrom
        cmp     word [rombuf], 0AA55h
        jne     .badrom
        mov     di, rombuf + ROMH_SIG
        mov     si, rom_sig
        mov     cx, 8
        push    es
        push    cs
        pop     es
        repe    cmpsb
        pop     es
        je      .romok
.badrom:
        mov     dx, msg_badrom
        jmp     die

.romok: mov     al, [chips]
        mov     cl, 4
        shl     al, cl                  ; 16 flash blocks per chip
        dec     al
        mov     [f_np], al              ; disk blocks 1 .. chips * 16 - 1
        test    byte [opt_flags], OPT_ERASE
        jnz     .erase

        ; without /E: keep the disk, its bad blocks and so its geometry
        xor     ax, ax
        mov     [d_bad], ax
        mov     [d_bad + 2], ax
        call    load_desc
        jnc     .layout
        xor     ax, ax                  ; no format 3 descriptor: no bad blocks known
        mov     [d_bad], ax
        mov     [d_bad + 2], ax
        jmp     .layout

.erase: PRINT   msg_ask_erase
        mov     dx, msg_ask
        call    ask_yes
        je      .etest
        mov     dx, msg_cancel
        jmp     die
.etest: call    vpp_test
        test    al, SR_VPP_LOW
        jz      .tst
        mov     dx, msg_jumper
        jmp     die
.tst:   xor     ax, ax
        mov     [d_bad], ax
        mov     [d_bad + 2], ax
        test    byte [opt_flags], OPT_TEST
        jz      .t0
        mov     byte [tb_full], 1
.t0:    mov     bl, 1
.t1:    call    test_one
        jnc     .t2
        mov     al, bl
        call    set_bad_d
.t2:    inc     bl
        cmp     bl, [f_np]
        jbe     .t1

.layout:                                ; good blocks -> logical blocks (one good block stays free, count even)
        xor     cl, cl
        mov     al, 1
.cnt:   call    is_bad_d
        jnz     .cn
        inc     cl
.cn:    inc     al
        cmp     al, [f_np]
        jbe     .cnt
        cmp     cl, 3
        jae     .nlok
        mov     dx, msg_toobad
        jmp     die
.nlok:  dec     cl
        and     cl, 0FEh
        mov     [f_nl], cl
        mov     al, cl
        xor     ah, ah
        shr     al, 1
        mov     [spt], ax
        mov     al, cl
        mov     cl, SECTORS_PER_LBLK
        mul     cl
        mov     [total], ax

        ; block 0 image: FFh, the ROM with the port and checksum, the descriptor
        push    es
        mov     es, [bufseg]
        xor     di, di
        mov     ax, 0FFFFh
        mov     cx, 8000h
        rep     stosw
        xor     di, di
        mov     si, rombuf
        mov     cx, ROM_SIZE / 2
        rep     movsw
        mov     ax, [port]
        mov     [es:ROMH_PORT], ax
        xor     si, si
        mov     cx, ROM_SIZE - 1
        xor     ah, ah
.rsum:  add     ah, [es:si]
        inc     si
        loop    .rsum
        neg     ah
        mov     [es:ROM_SIZE - 1], ah
        mov     di, DESC_LINEAR
        xor     ax, ax
        mov     cx, SECTOR_SIZE / 2
        rep     stosw
        mov     di, DESC_LINEAR
        mov     si, desc_sig
        mov     cx, 8
        rep     movsb
        mov     word [es:DESC_LINEAR + DESC_VERSION], DESC_FORMAT
        mov     al, [chips]
        mov     [es:DESC_LINEAR + DESC_CHIPS], al
        mov     al, [f_np]
        mov     [es:DESC_LINEAR + DESC_PBLKS], al
        mov     al, [f_nl]
        mov     [es:DESC_LINEAR + DESC_LBLKS], al
        mov     ax, [spt]
        mov     [es:DESC_LINEAR + DESC_SPT], ax
        mov     ax, [total]
        mov     [es:DESC_LINEAR + DESC_TOTAL], ax
        mov     word [es:DESC_LINEAR + DESC_CYLS], DISK_CYLS
        mov     word [es:DESC_LINEAR + DESC_HEADS], DISK_HEADS
        mov     word [es:DESC_LINEAR + DESC_DATA], DATA_FIRST_SECTOR
        mov     ax, [d_bad]
        mov     [es:DESC_LINEAR + DESC_BAD], ax
        mov     ax, [d_bad + 2]
        mov     [es:DESC_LINEAR + DESC_BAD + 2], ax
        mov     si, DESC_LINEAR
        mov     cx, SECTOR_SIZE - 1
        xor     ah, ah
.dsum:  add     ah, [es:si]
        inc     si
        loop    .dsum
        neg     ah
        mov     [es:DESC_LINEAR + DESC_CHECKSUM], ah
        pop     es

        PRINT   msg_plan1
        mov     ax, [port]
        call    print_hex16
        PRINT   msg_plan2
        mov     ax, DISK_CYLS
        call    print_dec
        PRINT   msg_plan3
        mov     ax, [spt]
        call    print_dec
        PRINT   msg_plan3b
        mov     ax, [total]
        shr     ax, 1
        call    print_dec
        PRINT   msg_plan4
        test    byte [opt_flags], OPT_ERASE
        jnz     .b0                     ; asked before the erase already
        mov     dx, msg_ask
        call    ask_yes
        je      .go
        mov     dx, msg_cancel
        jmp     die
.go:    call    vpp_test
        test    al, SR_VPP_LOW
        jz      .b0
        mov     dx, msg_jumper
        jmp     die
.b0:    PRINT   msg_block0
        xor     bl, bl
        call    write_block
        jnc     .b0ok
        jmp     .fail
.b0ok:  PRINT   msg_ok

        test    byte [opt_flags], OPT_ERASE
        jz      .check
        PRINT   msg_headers             ; empty disk: logical blocks 0.. in the good blocks, in order
        mov     byte [blk], 1
        mov     byte [lblk], 0
.hd:    mov     al, [blk]
        call    is_bad_d
        jnz     .hn
        mov     al, [lblk]
        cmp     al, [f_nl]
        jae     .hn
        push    es
        mov     es, [bufseg]
        xor     di, di
        mov     ax, 0FFFFh
        mov     cx, 8000h
        rep     stosw
        pop     es
        mov     al, [lblk]
        call    buf_header
        mov     bl, [blk]
        call    write_block             ; the block is erased: only the header is programmed
        jc      .fail
        inc     byte [lblk]
        mov     dl, '.'
        call    print_char
.hn:    inc     byte [blk]
        mov     al, [blk]
        cmp     al, [f_np]
        jbe     .hd
        call    print_crlf
        cmp     byte [n_bad], 0
        je      .done
        PRINT   msg_nbad1
        mov     al, [n_bad]
        xor     ah, ah
        call    print_dec
        PRINT   msg_nbad2
        jmp     .done

.check: call    load_desc               ; without /E the disk stays: it must already be format 3
        jc      .warn
        call    scan_map
        jnc     .done
.warn:  PRINT   msg_nomap

.done:  call    vpp_off
        call    card_safe
        call    remount
        PRINT   msg_done
        xor     al, al
        jmp     exit_prog

.fail:  push    ax
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

total           dw      0
spt             dw      0
blk             db      0
lblk            db      0
f_np            db      0
f_nl            db      0
desc_sig:       db      'ISAFLDSK'
msg_banner:     db      'FLFORMAT 1.2 - ISA Flash Disk', 13, 10, '$'
msg_usage:      db      'Usage: FLFORMAT romfile [/E [/T]] [/Y] [/M:seg] [/P:port]', 13, 10
                db      '  romfile  FLASHROM.BIN', 13, 10
                db      '  /E       also erase and test the disk blocks, leave bad ones out', 13, 10
                db      '  /T       with /E: full block test (00h pattern too)', 13, 10
                db      '  /Y       no confirmation', 13, 10, '$'
msg_nomem:      db      'Not enough memory (needs 128 KB).', 13, 10, '$'
msg_open:       db      'Cannot open the ROM file.', 13, 10, '$'
msg_badrom:     db      'Not an ISA Flash Disk ROM image (8192 bytes, 55AA, ISAFLASH).', 13, 10, '$'
msg_ask_erase:  db      'ERASE the whole disk, test every block and install the option ROM.', 13, 10, '$'
msg_toobad:     db      'Too many bad blocks for a disk.', 13, 10, '$'
msg_plan1:      db      'Option ROM (port $'
msg_plan2:      db      'h) and disk descriptor: C/H/S $'
msg_plan3:      db      '/2/$'
msg_plan3b:     db      ', $'
msg_plan4:      db      ' KB.', 13, 10, '$'
msg_ask:        db      'Continue? (Y/N) $'
msg_cancel:     db      'Cancelled.', 13, 10, '$'
msg_block0:     db      'Block 0 (ROM + descriptor): $'
msg_ok:         db      'OK', 13, 10, '$'
msg_headers:    db      'Empty disk: block headers $'
msg_nbad1:      db      'Bad blocks left out: $'
msg_nbad2:      db      '.', 13, 10, '$'
msg_nomap:      db      'The disk has no format 3 block map: run FLFORMAT with /E.', 13, 10, '$'
msg_fail:       db      'FAILED, status $'
msg_failend:    db      'h.', 13, 10, '$'
msg_done:       db      'Done. Restart the computer to load the new ROM.', 13, 10, '$'

        section .bss
fname:          resb    128
tmpbuf:         resb    WINDOW_SIZE
rombuf:         resb    ROM_SIZE + 16
