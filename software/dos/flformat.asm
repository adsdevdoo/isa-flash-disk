; FLFORMAT.COM - install the option ROM and the disk descriptor into flash block 0.
; Usage: FLFORMAT romfile [/E] [/Y] [/M:seg] [/P:port]
;   romfile  FLASHROM.BIN (8192 bytes); the card's I/O port is written into it and the checksum fixed
;   /E       also erase the whole disk and write an empty disk: block headers for logical blocks 0..n-1 in
;            flash blocks 1..n, the last flash block free
;   /Y       do not ask for confirmation
; Disk format 3 (docs/programming.md): logical blocks of 127 sectors, one flash block more than logical blocks.
; Geometry 127 cylinders x 2 heads x (logical blocks / 2): 1 chip = 127/2/7 (1778 sectors),
; 2 chips = 127/2/15 (3810 sectors). A disk of an older format must be erased (/E) and written again.
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

.mem:   ; block 0 image = FFh
        push    es
        mov     es, [bufseg]
        xor     di, di
        mov     ax, 0FFFFh
        mov     cx, 8000h
        rep     stosw
        pop     es
        ; ROM file -> buffer:0, must be exactly 8192 bytes
        mov     dx, fname
        mov     ax, 3D00h
        int     21h
        jnc     .opened
        mov     dx, msg_open
        jmp     die
.opened:
        mov     bx, ax
        push    ds
        mov     ds, [bufseg]
        xor     dx, dx
        mov     cx, ROM_SIZE + 1
        mov     ah, 3Fh
        int     21h
        pop     ds
        pushf
        push    ax
        mov     ah, 3Eh
        int     21h
        pop     ax
        popf
        jc      .badrom
        cmp     ax, ROM_SIZE
        jne     .badrom
        push    es
        mov     es, [bufseg]
        cmp     word [es:0], 0AA55h
        jne     .badrom_es
        mov     di, ROMH_SIG
        mov     si, rom_sig
        mov     cx, 8
        repe    cmpsb
        jne     .badrom_es
        ; port and checksum
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

        ; descriptor at 2000h
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
        mov     cl, 4
        shl     al, cl                  ; 16 flash blocks per chip
        dec     al
        mov     [es:DESC_LINEAR + DESC_PBLKS], al  ; data blocks 1 .. chips * 16 - 1
        mov     [f_np], al
        dec     al
        mov     [es:DESC_LINEAR + DESC_LBLKS], al  ; one physical block more than logical blocks
        mov     [f_nl], al
        xor     ah, ah
        push    ax
        shr     al, 1
        mov     [es:DESC_LINEAR + DESC_SPT], ax    ; 127 x 2 x (logical blocks / 2) = all sectors
        mov     [spt], ax
        pop     ax
        mov     cl, SECTORS_PER_LBLK
        mul     cl
        mov     [es:DESC_LINEAR + DESC_TOTAL], ax
        mov     [total], ax
        mov     word [es:DESC_LINEAR + DESC_CYLS], DISK_CYLS
        mov     word [es:DESC_LINEAR + DESC_HEADS], DISK_HEADS
        mov     word [es:DESC_LINEAR + DESC_DATA], DATA_FIRST_SECTOR
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
        jz      .ask
        PRINT   msg_plan_erase
.ask:   mov     dx, msg_ask
        call    ask_yes
        je      .go
        mov     dx, msg_cancel
        jmp     die

.go:    call    vpp_test
        test    al, SR_VPP_LOW
        jz      .vpp
        mov     dx, msg_jumper
        jmp     die
.vpp:   PRINT   msg_block0
        xor     bl, bl
        call    write_block
        jnc     .b0ok
        jmp     .fail
.b0ok:  PRINT   msg_ok

        test    byte [opt_flags], OPT_ERASE
        jz      .check
        PRINT   msg_erasing
        mov     byte [blk], 1
.er:    push    es                      ; flash block blk = FFh with the header of logical block blk - 1,
        mov     es, [bufseg]            ; the last one stays free
        xor     di, di
        mov     ax, 0FFFFh
        mov     cx, 8000h
        rep     stosw
        pop     es
        mov     al, [blk]
        cmp     al, [f_np]
        je      .nohdr
        dec     al
        call    buf_header
.nohdr: mov     bl, [blk]
        call    write_block
        jc      .fail
        mov     dl, '.'
        call    print_char
        inc     byte [blk]
        mov     al, [blk]
        cmp     al, [f_np]
        jbe     .er
        call    print_crlf
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

.badrom_es:
        pop     es
.badrom:
        mov     dx, msg_badrom
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
f_np            db      0
f_nl            db      0
desc_sig:       db      'ISAFLDSK'
msg_banner:     db      'FLFORMAT 1.2 - ISA Flash Disk', 13, 10, '$'
msg_usage:      db      'Usage: FLFORMAT romfile [/E] [/Y] [/M:seg] [/P:port]', 13, 10
                db      '  romfile  FLASHROM.BIN', 13, 10
                db      '  /E       also erase the whole disk area', 13, 10
                db      '  /Y       no confirmation', 13, 10, '$'
msg_nomem:      db      'Not enough memory (needs 128 KB).', 13, 10, '$'
msg_open:       db      'Cannot open the ROM file.', 13, 10, '$'
msg_badrom:     db      'Not an ISA Flash Disk ROM image (8192 bytes, 55AA, ISAFLASH).', 13, 10, '$'
msg_plan1:      db      'Install the option ROM (port $'
msg_plan2:      db      'h) and the disk descriptor: C/H/S $'
msg_plan3:      db      '/2/$'
msg_plan3b:     db      ', $'
msg_plan4:      db      ' KB.', 13, 10, '$'
msg_plan_erase: db      'ERASE the whole disk area as well.', 13, 10, '$'
msg_ask:        db      'Continue? (Y/N) $'
msg_cancel:     db      'Cancelled.', 13, 10, '$'
msg_block0:     db      'Block 0 (ROM + descriptor): $'
msg_ok:         db      'OK', 13, 10, '$'
msg_erasing:    db      'Erasing the disk $'
msg_nomap:      db      'The disk has no format 3 block map: run FLFORMAT with /E.', 13, 10, '$'
msg_fail:       db      'FAILED, status $'
msg_failend:    db      'h.', 13, 10, '$'
msg_done:       db      'Done. Restart the computer to load the new ROM.', 13, 10, '$'

        section .bss
fname:          resb    128
tmpbuf:         resb    WINDOW_SIZE
