; FLREAD.COM - copy the flash (or only the disk) to a file.
; Usage: FLREAD file [/D] [/M:seg] [/P:port]
;   /D  the disk only (disk format 3): logical blocks in order, by the block map, inverted back - a plain hard
;       disk image for FLWRITE /D and for PC emulators
; Without /D: the raw flash, every chip from address 0 (ROM, descriptor, blocks with their headers).

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
        test    byte [opt_flags], OPT_DISK
        jz      .create
        call    load_desc
        jnc     .desc
        mov     dx, msg_nodisk
        jmp     die
.desc:  call    scan_map
        jnc     .create
        mov     dx, msg_nomap
        jmp     die

.create:
        mov     dx, fname
        xor     cx, cx
        mov     ah, 3Ch
        int     21h
        jnc     .open
        mov     dx, msg_create
        jmp     die
.open:  mov     [handle], ax
        test    byte [opt_flags], OPT_DISK
        jnz     .disk

        ; raw: every bank of every chip
        mov     al, [chips]
        xor     ah, ah
        mov     cl, 7
        shl     ax, cl                  ; 128 banks per chip
        mov     [last], ax
        mov     word [bank], 0
.next:  mov     ax, [bank]
        call    set_bank
        call    copy_bank
        xor     al, al
        call    set_bank
        mov     cx, WINDOW_SIZE
        call    put_tmp
        mov     ax, [bank]
        inc     ax
        mov     [bank], ax
        test    al, BANKS_PER_BLOCK - 1
        jnz     .nodot
        mov     dl, '.'
        call    print_char
.nodot: cmp     ax, [last]
        jb      .next
        jmp     .close

.disk:  mov     byte [lblk], 0          ; logical blocks in order: 127 data sectors each, header left out
.dblk:  xor     bh, bh
        mov     bl, [lblk]
        mov     al, [fmap + bx]
        mov     cl, 3
        shl     al, cl
        mov     [bank], ax
        mov     byte [bidx], 0
.dbank: mov     al, [bank]
        add     al, [bidx]
        call    set_bank
        call    copy_bank
        xor     al, al
        call    set_bank
        mov     si, tmpbuf              ; stored inverted
        mov     cx, WINDOW_SIZE / 2
.inv:   not     word [si]
        inc     si
        inc     si
        loop    .inv
        mov     cx, WINDOW_SIZE
        cmp     byte [bidx], HDR_BANK
        jne     .put
        mov     cx, HDR_WOFF
.put:   call    put_tmp
        inc     byte [bidx]
        cmp     byte [bidx], BANKS_PER_BLOCK
        jb      .dbank
        mov     dl, '.'
        call    print_char
        inc     byte [lblk]
        mov     al, [lblk]
        cmp     al, [d_nl]
        jb      .dblk

.close: mov     bx, [handle]
        mov     ah, 3Eh
        int     21h
        call    print_crlf
        PRINT   msg_done
        xor     al, al
        jmp     exit_prog

usage:  PRINT   msg_usage
        mov     al, 2
        mov     ah, 4Ch
        int     21h

; copy_bank: the window (bank already selected) -> tmpbuf
copy_bank:
        push    cx
        push    si
        push    di
        push    ds
        push    es
        mov     ds, [winseg]
        push    cs
        pop     es
        xor     si, si
        mov     di, tmpbuf
        mov     cx, WINDOW_SIZE / 2
        rep     movsw
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     cx
        ret

; put_tmp: CX bytes of tmpbuf -> the file; dies on a write error
put_tmp:
        push    cx
        mov     bx, [handle]
        mov     dx, tmpbuf
        mov     ah, 40h
        int     21h
        pop     cx
        jc      .err
        cmp     ax, cx
        jne     .err
        ret
.err:   mov     dx, msg_write
        jmp     die

%include "doslib.inc"
%include "flashlib.inc"

bank            dw      0
last            dw      0
handle          dw      0
lblk            db      0
bidx            db      0
msg_banner:     db      'FLREAD 1.2 - ISA Flash Disk', 13, 10, '$'
msg_usage:      db      'Usage: FLREAD file [/D] [/M:seg] [/P:port]', 13, 10
                db      '  /D  the disk only (hard disk image)', 13, 10, '$'
msg_nodisk:     db      'No format 3 disk on the card (FLFORMAT /E, then FLWRITE /D).', 13, 10, '$'
msg_nomap:      db      'Disk block map damaged.', 13, 10, '$'
msg_create:     db      'Cannot create the file.', 13, 10, '$'
msg_write:      db      13, 10, 'Write error (disk full?).', 13, 10, '$'
msg_done:       db      'Done.', 13, 10, '$'

        section .bss
fname:          resb    128
tmpbuf:         resb    WINDOW_SIZE
