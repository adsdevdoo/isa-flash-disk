; FLTEST.COM - test the flash blocks for wear and defects (salvaged chips may be worn).
; Usage: FLTEST [/A] [/Y] [/M:seg] [/P:port]
;   without /A: every disk block of a format 3 disk, the data are kept. The free block is tested, then a logical
;       block is moved into it the same way a disk write does it (header with a new generation written last),
;       and the flash block it left is tested next, until every disk block has been tested.
;   /A  every flash block including block 0 (ROM and descriptor): ERASES EVERYTHING; afterwards FLFORMAT /E.
; Test of one block: erase (timed), every byte FFh, program 00h into every byte and verify, erase again (timed),
; every byte FFh. The 28F008SA erases a block in typ. 1.6 s, max 10 s (DS p. 34); erase time grows with wear.
; Result: OK; WORN = an erase took longer than 5 s; BAD = longer than 10 s or any error.
; FLFORMAT /E /T runs the same test and leaves bad blocks out of the disk.
; Exit code: 0 all blocks OK, 4 some block WORN, 5 some block BAD, 1 other error. Needs the WRITE jumper JP1.

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
        call    alloc_buffer
        jnc     .mem
        mov     dx, msg_nomem
        jmp     die
.mem:   mov     byte [tb_full], 1
        test    byte [opt_flags], OPT_ALL
        jz      .disk
        jmp     all_blocks

.disk:  call    load_desc
        jnc     .desc
        mov     dx, msg_nodisk
        jmp     die
.desc:  call    scan_map
        jnc     .map
        mov     dx, msg_nomap
        jmp     die
.map:   PRINT   msg_ask_disk1
        mov     al, [d_nl]
        xor     ah, ah
        inc     ax
        call    print_dec
        PRINT   msg_ask_disk2
        mov     dx, msg_yn
        call    ask_yes
        je      .go
        mov     dx, msg_cancel
        jmp     die
.go:    call    vpp_test
        test    al, SR_VPP_LOW
        jz      .loop
        mov     dx, msg_jumper
        jmp     die

.loop:  mov     bl, [fl_free]           ; the free block holds nothing: test it
        xor     bh, bh
        mov     byte [tested + bx], 1
        call    test_one
        jc      .stopbad
        xor     bx, bx                  ; next logical block whose flash block was not tested yet
.find:  mov     al, [fmap + bx]
        xor     ah, ah
        mov     si, ax
        cmp     byte [tested + si], 0
        je      .move
        inc     bx
        cmp     bl, [d_nl]
        jb      .find
        jmp     finish
.move:  call    move_lblk
        jnc     .loop
        push    ax
        PRINT   msg_mvfail
        pop     ax
        call    print_hex8
        PRINT   msg_mvfail2
        mov     byte [n_bad], 1
        jmp     finish
.stopbad:
        PRINT   msg_freebad
        jmp     finish

all_blocks:
        PRINT   msg_ask_all
        mov     dx, msg_yn
        call    ask_yes
        je      .go
        mov     dx, msg_cancel
        jmp     die
.go:    call    vpp_test
        test    al, SR_VPP_LOW
        jz      .run
        mov     dx, msg_jumper
        jmp     die
.run:   mov     al, [chips]
        mov     cl, 4
        shl     al, cl
        mov     [nblk], al
        xor     bl, bl
.next:  call    test_one
        inc     bl
        cmp     bl, [nblk]
        jb      .next
        PRINT   msg_format

finish: call    vpp_off
        call    card_safe
        call    remount
        PRINT   msg_sum1
        mov     al, [n_good]
        xor     ah, ah
        call    print_dec
        PRINT   msg_sum2
        mov     al, [n_worn]
        xor     ah, ah
        call    print_dec
        PRINT   msg_sum3
        mov     al, [n_bad]
        xor     ah, ah
        call    print_dec
        PRINT   msg_sum4
        xor     al, al
        cmp     byte [n_worn], 0
        je      .b
        mov     al, 4
.b:     cmp     byte [n_bad], 0
        je      .x
        mov     al, 5
.x:     jmp     exit_prog

usage:  PRINT   msg_usage
        mov     al, 2
        mov     ah, 4Ch
        int     21h

; move_lblk: BL = logical block -> copied into the free block (raw, with a new header written last); the block
; it left becomes the free block. CF = error, AL = status.
move_lblk:
        push    bx
        push    cx
        push    si
        push    di
        push    ds
        push    es
        mov     [mv_l], bl
        xor     bh, bh
        mov     al, [fmap + bx]
        mov     [mv_src], al
        mov     es, [bufseg]
        xor     di, di
        xor     ah, ah                  ; bank index
.bank:  mov     al, [cs:mv_src]
        mov     cl, 3
        shl     al, cl
        add     al, ah
        call    set_bank
        push    ds
        mov     ds, [cs:winseg]
        xor     si, si
        mov     cx, WINDOW_SIZE / 2
        rep     movsw                   ; DI runs on through the 64 KB buffer
        pop     ds
        inc     ah
        cmp     ah, BANKS_PER_BLOCK
        jb      .bank
        xor     al, al
        call    set_bank
        mov     di, SECTORS_PER_LBLK * SECTOR_SIZE   ; old header -> FFh, then the new one
        mov     al, 0FFh
        mov     cx, SECTOR_SIZE
        rep     stosb
        mov     al, [mv_l]
        call    buf_header
        mov     bl, [fl_free]
        call    write_block
        jc      .err
        xor     bh, bh
        mov     bl, [mv_l]
        mov     al, [fl_free]
        mov     [fmap + bx], al
        mov     al, [mv_src]
        mov     [fl_free], al
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     cx
        pop     bx
        clc
        ret
.err:   pop     es
        pop     ds
        pop     di
        pop     si
        pop     cx
        pop     bx
        stc
        ret

%include "doslib.inc"
%include "flashlib.inc"

nblk            db      0
mv_l            db      0
mv_src          db      0
tested:         times 32 db 0
msg_banner:     db      'FLTEST 1.2 - ISA Flash Disk', 13, 10, '$'
msg_usage:      db      'Usage: FLTEST [/A] [/Y] [/M:seg] [/P:port]', 13, 10
                db      '  (no /A)  test every disk block, the data are kept', 13, 10
                db      '  /A       test every flash block: ERASES EVERYTHING', 13, 10
                db      '  /Y       no confirmation', 13, 10, '$'
msg_nomem:      db      'Not enough memory (needs 128 KB).', 13, 10, '$'
msg_nodisk:     db      'No format 3 disk: FLTEST /A tests every block but erases the whole flash.', 13, 10, '$'
msg_nomap:      db      'Disk block map damaged: FLTEST /A, then FLFORMAT /E.', 13, 10, '$'
msg_ask_disk1:  db      'Test $'
msg_ask_disk2:  db      ' disk blocks; the data are kept; takes minutes.', 13, 10, '$'
msg_ask_all:    db      'ERASE THE WHOLE FLASH, the option ROM too, and test every block.', 13, 10, '$'
msg_yn:         db      'Continue? (Y/N) $'
msg_cancel:     db      'Cancelled.', 13, 10, '$'
msg_freebad:    db      'Stopped: the free block is bad. The data are kept. Save them (FLREAD /D),', 13, 10
                db      'then FLFORMAT /E /T leaves bad blocks out of the disk.', 13, 10, '$'
msg_mvfail:     db      'Moving a block FAILED, status $'
msg_mvfail2:    db      'h. The old copy is still in force.', 13, 10, '$'
msg_format:     db      'Now run FLFORMAT FLASHROM.BIN /E: it leaves bad blocks out.', 13, 10, '$'
msg_sum1:       db      'OK: $'
msg_sum2:       db      ', WORN: $'
msg_sum3:       db      ', BAD: $'
msg_sum4:       db      13, 10, '$'

        section .bss
fname:          resb    128
tmpbuf:         resb    WINDOW_SIZE
