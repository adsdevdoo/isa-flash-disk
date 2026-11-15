; FLREAD.COM - copy the flash (or only the disk area) to a file.
; Usage: FLREAD file [/D] [/M:seg] [/P:port]
;   /D  disk area only (from 64 KB on, without the spare block, inverted back): a hard disk image for
;       FLWRITE /D and for PC emulators

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

        xor     ax, ax                  ; first bank
        test    byte [opt_flags], OPT_DISK
        jz      .full
        mov     ax, DATA_LINEAR / WINDOW_SIZE
.full:  mov     [bank], ax
        mov     al, [chips]
        xor     ah, ah
        mov     cl, 7
        shl     ax, cl                  ; 128 banks per chip
        test    byte [opt_flags], OPT_DISK
        jz      .lastok
        sub     ax, BANKS_PER_BLOCK     ; the spare block is not part of the disk
.lastok:
        mov     [last], ax

        mov     dx, fname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jnc     .open
        mov     dx, msg_create
        jmp     die
.open:  mov     [handle], ax

.next:  mov     ax, [bank]
        call    set_bank
        push    ds
        push    es
        mov     ds, [winseg]
        push    cs
        pop     es
        xor     si, si
        mov     di, tmpbuf
        mov     cx, WINDOW_SIZE / 2
        test    byte [cs:opt_flags], OPT_DISK
        jz      .raw
.inv:   lodsw
        not     ax                      ; disk format 2 is stored inverted
        stosw
        loop    .inv
        jmp     .copied
.raw:   rep     movsw
.copied:
        pop     es
        pop     ds
        xor     al, al
        call    set_bank
        mov     bx, [handle]
        mov     dx, tmpbuf
        mov     cx, WINDOW_SIZE
        mov     ah, 40h
        int     21h
        jc      .werr
        cmp     ax, WINDOW_SIZE
        jne     .werr
        mov     ax, [bank]
        inc     ax
        mov     [bank], ax
        test    al, BANKS_PER_BLOCK - 1
        jnz     .nodot
        mov     dl, '.'
        call    print_char
.nodot: cmp     ax, [last]
        jb      .next

        mov     bx, [handle]
        mov     ah, 3Eh
        int     21h
        call    print_crlf
        PRINT   msg_done
        xor     al, al
        jmp     exit_prog

.werr:  mov     dx, msg_write
        jmp     die

usage:  PRINT   msg_usage
        mov     al, 2
        mov     ah, 4Ch
        int     21h

%include "doslib.inc"
%include "flashlib.inc"

bank            dw      0
last            dw      0
handle          dw      0
msg_banner:     db      'FLREAD 1.1 - ISA Flash Disk', 13, 10, '$'
msg_usage:      db      'Usage: FLREAD file [/D] [/M:seg] [/P:port]', 13, 10
                db      '  /D  disk area only (hard disk image)', 13, 10, '$'
msg_create:     db      'Cannot create the file.', 13, 10, '$'
msg_write:      db      13, 10, 'Write error (disk full?).', 13, 10, '$'
msg_done:       db      'Done.', 13, 10, '$'

        section .bss
fname:          resb    128
tmpbuf:         resb    WINDOW_SIZE
