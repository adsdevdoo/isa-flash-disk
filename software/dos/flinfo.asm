; FLINFO.COM - find the ISA Flash Disk card and report what is on it.
; Usage: FLINFO [/J] [/M:seg] [/P:port]
;   /J  test the WRITE jumper JP1 (switches VPP on and programs FFh over the first ROM byte: no bit can change)

        cpu     8086
        bits    16
        org     100h

%include "isaflash.inc"
%include "dosmacro.inc"

start:  cld
        mov     byte [fname], 0
        call    parse_args
        jc      usage
        PRINT   msg_banner
        call    install_break
        call    card_find
        jnc     .found
        jmp     not_found
.found: call    print_card

        ; option ROM
        cmp     byte [rom_found], 0
        je      .norom
        PRINT   msg_rom1
        push    es
        mov     es, [winseg]
        mov     al, [es:ROMH_VERSION]
        xor     ah, ah
        call    print_dec
        mov     dl, '.'
        call    print_char
        mov     al, [es:ROMH_VERSION + 1]
        call    print_dec
        PRINT   msg_rom2
        mov     ax, [es:ROMH_PORT]
        pop     es
        call    print_hex16
        PRINT   msg_h_crlf
        jmp     .ids
.norom: PRINT   msg_norom

.ids:   PRINT   msg_u1
        mov     ax, FL_DEV_28F008SA * 256 + FL_MFR_INTEL
        call    print_id
        PRINT   msg_u2
        cmp     byte [chips], 2
        je      .u2
        PRINT   msg_notfitted
        jmp     .desc
.u2:    mov     ax, [id1]
        call    print_id

.desc:  call    load_desc
        jnc     .d3
        mov     dx, msg_nodesc
        cmp     al, 1
        je      .dmsg
        mov     dx, msg_baddesc
        cmp     al, 2
        je      .dmsg
        PRINT   msg_old1
        mov     ax, [dbuf + DESC_VERSION]
        call    print_dec
        mov     dx, msg_old2
.dmsg:  call    print_dollar
        jmp     .jumper
.d3:    PRINT   msg_disk1
        mov     ax, [dbuf + DESC_CYLS]
        call    print_dec
        mov     dl, '/'
        call    print_char
        mov     ax, [dbuf + DESC_HEADS]
        call    print_dec
        mov     dl, '/'
        call    print_char
        mov     ax, [dbuf + DESC_SPT]
        call    print_dec
        PRINT   msg_disk2
        mov     ax, [dbuf + DESC_TOTAL]
        call    print_dec
        PRINT   msg_disk3
        mov     ax, [dbuf + DESC_TOTAL]
        shr     ax, 1
        call    print_dec
        PRINT   msg_disk4
        call    scan_map
        jnc     .map
        PRINT   msg_nomap
        jmp     .jumper
.map:   PRINT   msg_map1
        mov     al, [d_nl]
        xor     ah, ah
        call    print_dec
        PRINT   msg_map2
        mov     al, [d_np]
        xor     ah, ah
        call    print_dec
        PRINT   msg_map3
        mov     al, [fl_free]
        xor     ah, ah
        call    print_dec
        PRINT   msg_map4
        mov     ax, [fseq + 2]
        call    print_hex16
        mov     ax, [fseq]
        call    print_hex16
        PRINT   msg_h_crlf

.jumper:
        test    byte [opt_flags], OPT_JUMPER
        jz      .end
        call    vpp_test
        push    ax
        call    card_safe
        pop     ax
        test    al, SR_VPP_LOW
        jz      .vok
        PRINT   msg_jp_open
        jmp     .end
.vok:   PRINT   msg_jp_fitted
.end:   xor     al, al
        jmp     exit_prog

usage:  PRINT   msg_usage
        mov     al, 2
        mov     ah, 4Ch
        int     21h

; print_id: AX = ID (AL manufacturer, AH device)
print_id:
        push    ax
        call    print_hex8
        mov     dl, ' '
        call    print_char
        mov     al, ah
        call    print_hex8
        pop     ax
        cmp     ax, FL_DEV_28F008SA * 256 + FL_MFR_INTEL
        jne     .other
        PRINT   msg_intel
        ret
.other: PRINT   msg_unknown
        ret

%include "doslib.inc"
%include "flashlib.inc"

desc_sig:       db      'ISAFLDSK'
msg_banner:     db      'FLINFO 1.2 - ISA Flash Disk', 13, 10, '$'
msg_usage:      db      'Usage: FLINFO [/J] [/M:seg] [/P:port]', 13, 10
                db      '  /J  test the WRITE jumper JP1', 13, 10, '$'
msg_rom1:       db      'Option ROM: version $'
msg_rom2:       db      ', port in ROM $'
msg_h_crlf:     db      'h', 13, 10, '$'
msg_norom:      db      'Option ROM: not found (run FLFORMAT)', 13, 10, '$'
msg_u1:         db      'U1: $'
msg_u2:         db      'U2: $'
msg_notfitted:  db      'not fitted', 13, 10, '$'
msg_intel:      db      ' (Intel 28F008SA)', 13, 10, '$'
msg_unknown:    db      ' (unknown)', 13, 10, '$'
msg_disk1:      db      'Disk: C/H/S $'
msg_disk2:      db      ', $'
msg_disk3:      db      ' sectors ($'
msg_disk4:      db      ' KB), format 3', 13, 10, '$'
msg_old1:       db      'Disk: format $'
msg_old2:       db      ' (old): run FLFORMAT /E and write the disk again', 13, 10, '$'
msg_nomap:      db      'Block map: damaged (run FLFORMAT /E)', 13, 10, '$'
msg_map1:       db      'Blocks: $'
msg_map2:       db      ' logical in $'
msg_map3:       db      ' flash blocks, free block $'
msg_map4:       db      ', generation $'
msg_nodesc:     db      'Disk: no descriptor (run FLFORMAT)', 13, 10, '$'
msg_baddesc:    db      'Disk: descriptor checksum error', 13, 10, '$'
msg_jp_open:    db      'WRITE jumper JP1: open (VPP low, flash protected)', 13, 10, '$'
msg_jp_fitted:  db      'WRITE jumper JP1: fitted (VPP present)', 13, 10, '$'

        section .bss
fname:          resb    128
tmpbuf:         resb    WINDOW_SIZE
