; ISA Flash Disk option ROM (8 KB, lives in flash bank 0 of chip U1).
;
; Build:  nasm -f bin -I ../include/ -o FLASHROM.BIN flashrom.asm   (tools/build_dos.py also fixes the checksum)
;
; The BIOS finds the ROM in the 8 KB window (XT Technical Reference 5-10) and far-calls offset 3.
; init runs from the window: it takes 2 KB from the top of base memory (word 40h:13h) and copies the
; resident part there. Only the resident part may switch banks, because the ROM disappears from the window
; as soon as another bank is selected: init far-calls the RAM copy of read_desc to fetch the descriptor
; from bank 1, then validates it, installs an INT 13h hard disk (read and write) and, when the disk became 80h,
; an INT 19h handler that boots from A: first and from the flash disk next.
;
; Bank 0 rule (docs/architecture.md): every routine leaves BANK = 0 and CTRL = 0 with interrupts enabled,
; so a warm boot (Ctrl-Alt-Del does not pulse RESET DRV) still finds this ROM.

        cpu     8086
        bits    16

%include "isaflash.inc"

RES_KB  equ     2                       ; resident part size in KB taken from base memory
TICKS_ERASE equ 400                     ; 22 s; block erase is at most 10 s (datasheet p. 34)

; =====================================================================================================
        section .text start=0
rom_start:
        db      55h, 0AAh
        db      ROM_SIZE / 512
        jmp     near init               ; entry point at offset 3

        times ROMH_SIG - ($ - rom_start) db 0
        db      'ISAFLASH'
cfg_port:
        dw      DEFAULT_PORT            ; ROMH_PORT, patched by FLFORMAT for the SW2 setting
        db      1, 1                    ; ROMH_VERSION
        db      'ISA Flash Disk option ROM 1.1', 0

init:
        push    ax
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    bp
        push    ds
        push    es
        cld
        mov     ax, 40h
        mov     ds, ax
        mov     ax, [13h]               ; base memory in KB
        sub     ax, RES_KB
        mov     [13h], ax
        mov     cl, 6
        shl     ax, cl                  ; KB -> paragraphs
        mov     es, ax                  ; ES = resident segment for the rest of init
        push    cs
        pop     ds
        mov     si, res_load
        xor     di, di
        mov     cx, res_size
        rep     movsb
        mov     [es:r_winseg], cs
        mov     ax, [cfg_port]
        mov     [es:r_port], ax

        ; far call to the RAM copy of read_desc (the descriptor is in bank 1)
        push    cs
        mov     ax, .back
        push    ax
        push    es
        mov     ax, read_desc
        push    ax
        retf
.back:  cmp     byte [es:r_valid], 1
        jne     .bad

        ; sanity: 1..1024 cylinders, 1..255 heads, 1..63 sectors, total fits the geometry
        mov     ax, [es:r_cyls]
        or      ax, ax
        jz      .bad
        cmp     ax, 1024
        ja      .bad
        mov     ax, [es:r_heads]
        or      ax, ax
        jz      .bad
        cmp     ax, 255
        ja      .bad
        mov     ax, [es:r_spt]
        or      ax, ax
        jz      .bad
        cmp     ax, 63
        ja      .bad
        mov     ax, [es:r_cyls]
        mul     word [es:r_heads]
        mul     word [es:r_spt]
        or      dx, dx
        jnz     .bad
        cmp     ax, [es:r_total]
        jb      .bad

        ; drive number: the next hard disk; INT 19h only when it is the first one
        xor     ax, ax
        mov     ds, ax
        mov     al, [475h]
        or      al, 80h
        mov     [es:r_drive], al
        inc     byte [475h]
        cli
        mov     ax, [13h*4]
        mov     [es:r_old13], ax
        mov     ax, [13h*4+2]
        mov     [es:r_old13+2], ax
        mov     word [13h*4], int13
        mov     [13h*4+2], es
        cmp     byte [es:r_drive], 80h
        jne     .no19
        mov     ax, [19h*4]
        mov     [es:r_old19], ax
        mov     ax, [19h*4+2]
        mov     [es:r_old19+2], ax
        mov     word [19h*4], int19
        mov     [19h*4+2], es
.no19:  sti
        push    cs
        pop     ds
        mov     si, msg_head
        call    print
        mov     ax, [es:r_total]
        shr     ax, 1                   ; sectors -> KB
        call    print_dec
        mov     si, msg_kb
        call    print
        mov     al, [es:r_drive]
        call    print_hex8
        mov     si, msg_port
        call    print
        mov     ax, [es:r_port]
        call    print_hex16
        mov     si, msg_rom
        call    print
        mov     ax, [es:r_winseg]
        call    print_hex16
        mov     si, msg_end
        call    print
        jmp     .done

.bad:   mov     ax, 40h
        mov     ds, ax
        add     word [13h], RES_KB      ; give the memory back
        push    cs
        pop     ds
        mov     si, msg_head
        call    print
        mov     si, msg_nodisk
        call    print
.done:  pop     es
        pop     ds
        pop     bp
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        retf

; ---- console output from the ROM (INT 10h teletype), DS:SI = text ----
print:  push    ax
        push    bx
.loop:  lodsb
        or      al, al
        jz      .end
        mov     ah, 0Eh
        xor     bx, bx
        int     10h
        jmp     .loop
.end:   pop     bx
        pop     ax
        ret

print_hex16:
        push    ax
        mov     al, ah
        call    print_hex8
        pop     ax
print_hex8:
        push    ax
        push    cx
        mov     cl, 4
        mov     ah, al
        shr     al, cl
        call    .nib
        mov     al, ah
        and     al, 0Fh
        call    .nib
        pop     cx
        pop     ax
        ret
.nib:   push    ax
        push    bx
        add     al, '0'
        cmp     al, '9'
        jbe     .out
        add     al, 'A' - '9' - 1
.out:   mov     ah, 0Eh
        xor     bx, bx
        int     10h
        pop     bx
        pop     ax
        ret

print_dec:                              ; AX unsigned
        push    ax
        push    bx
        push    cx
        push    dx
        mov     bx, 10
        xor     cx, cx
.div:   xor     dx, dx
        div     bx
        push    dx
        inc     cx
        or      ax, ax
        jnz     .div
.put:   pop     ax
        add     al, '0'
        mov     ah, 0Eh
        push    bx
        xor     bx, bx
        int     10h
        pop     bx
        loop    .put
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret

msg_head:       db      'ISA Flash Disk: ', 0
msg_kb:         db      ' KB, drive ', 0
msg_port:       db      'h, port ', 0
msg_rom:        db      'h, ROM ', 0
msg_end:        db      '0h', 13, 10, 0
msg_nodisk:     db      'no disk descriptor, run FLFORMAT', 13, 10, 0

res_load equ    section.res.start

; =====================================================================================================
        section res vstart=0 follows=.text align=16
res_begin:

; ---- read_desc: far-called once by init; copies the descriptor fields from bank 1 ----
read_desc:
        push    ax
        push    cx
        push    dx
        push    si
        push    di
        push    ds
        push    es
        push    cs
        pop     ds
        mov     byte [r_valid], 0
        mov     dx, [r_port]
        xor     al, al
        inc     dx
        out     dx, al                  ; CTRL = 0: no WE#, no VPP
        dec     dx
        mov     al, DESC_LINEAR / WINDOW_SIZE
        cli
        out     dx, al                  ; descriptor bank: the ROM is gone from the window now
        mov     es, [r_winseg]
        xor     di, di
        mov     si, desc_sig
        mov     cx, 8
        repe    cmpsb
        jne     .out
        xor     si, si
        mov     cx, SECTOR_SIZE
        xor     ah, ah
.sum:   add     ah, [es:si]
        inc     si
        loop    .sum
        or      ah, ah
        jnz     .out
        cmp     word [es:DESC_VERSION], DESC_FORMAT
        jne     .out
        mov     ax, [es:DESC_CYLS]
        mov     [r_cyls], ax
        mov     ax, [es:DESC_HEADS]
        mov     [r_heads], ax
        mov     ax, [es:DESC_SPT]
        mov     [r_spt], ax
        mov     ax, [es:DESC_TOTAL]
        mov     [r_total], ax
        mov     ax, [es:DESC_DATA]
        mov     [r_data], ax
        mov     al, [es:DESC_SPARE]
        mov     [r_spare], al
        mov     byte [r_valid], 1
.out:   xor     al, al
        out     dx, al                  ; bank 0: the ROM is back
        sti
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     ax
        retf

; ---- INT 13h: hard disk; data are stored inverted (format 2) ----
int13:
        cmp     dl, [cs:r_drive]
        je      .ours
        jmp     far [cs:r_old13]
.ours:  sti
        cld
        cmp     ah, 02h
        je      i13_read
        cmp     ah, 03h
        je      i13_write
        cmp     ah, 08h
        je      i13_params
        cmp     ah, 15h
        je      i13_type
        cmp     ah, 01h
        je      i13_status
        cmp     ah, 00h                 ; reset
        je      i13_ok
        cmp     ah, 04h                 ; verify
        je      i13_ok
        cmp     ah, 05h                 ; format track: nothing to do on flash
        je      i13_ok
        cmp     ah, 09h                 ; init drive parameters
        je      i13_ok
        cmp     ah, 0Ch                 ; seek
        je      i13_ok
        cmp     ah, 0Dh                 ; alternate reset
        je      i13_ok
        cmp     ah, 10h                 ; test ready
        je      i13_ok
        cmp     ah, 11h                 ; recalibrate
        je      i13_ok
        mov     ah, 01h                 ; invalid function
        jmp     i13_err

i13_ok: xor     ah, ah
        mov     [cs:r_status], ah
        clc
        retf    2
i13_err:
        mov     [cs:r_status], ah
        stc
        retf    2

i13_status:
        mov     al, [cs:r_status]
        xor     ah, ah
        clc
        retf    2

i13_type:
        mov     ah, 03h                 ; fixed disk
        xor     cx, cx
        mov     dx, [cs:r_total]
        clc
        retf    2

i13_params:
        mov     ax, [cs:r_cyls]
        dec     ax                      ; highest cylinder
        mov     ch, al
        mov     al, ah
        ror     al, 1
        ror     al, 1
        and     al, 0C0h
        or      al, [cs:r_spt]
        mov     cl, al
        mov     dh, [cs:r_heads]
        dec     dh
        push    es
        mov     ax, 40h
        mov     es, ax
        mov     dl, [es:75h]
        pop     es
        xor     ax, ax
        mov     [cs:r_status], al
        clc
        retf    2

; chs_lin: AL = count, CH/CL/DH = C/H/S (BIOS packing) -> BP = linear sector on the card, t_left = count.
; CF = outside the disk. Destroys AX, CX, DX.
chs_lin:
        mov     [cs:t_left], al
        mov     byte [cs:t_done], 0
        or      al, al
        jz      .bad
        mov     al, cl
        and     al, 3Fh
        jz      .bad
        cmp     al, [cs:r_spt]
        ja      .bad
        mov     [cs:t_sec], al
        cmp     dh, [cs:r_heads]
        jae     .bad
        mov     [cs:t_head], dh
        mov     al, ch
        mov     ah, cl
        mov     cl, 6
        shr     ah, cl                  ; AX = cylinder
        cmp     ax, [cs:r_cyls]
        jae     .bad
        mul     word [cs:r_heads]
        add     al, [cs:t_head]
        adc     ah, 0
        mul     word [cs:r_spt]
        mov     cl, [cs:t_sec]
        dec     cl
        xor     ch, ch
        add     ax, cx                  ; AX = LBA
        mov     cl, [cs:t_left]
        add     cx, ax
        cmp     cx, [cs:r_total]
        ja      .bad
        add     ax, [cs:r_data]
        mov     bp, ax
        clc
        ret
.bad:   stc
        ret

; norm_buf: ES:BX -> w_seg:w_off with w_off < 16, so 512-byte steps never wrap a segment
norm_buf:
        mov     ax, bx
        mov     cl, 4
        shr     ax, cl
        mov     cx, es
        add     ax, cx
        mov     [cs:w_seg], ax
        mov     ax, bx
        and     ax, 0Fh
        mov     [cs:w_off], ax
        ret

; AH=02h: read
i13_read:
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    ds
        push    es
        push    bp
        call    chs_lin
        jc      i13_badsec
        call    norm_buf
        mov     es, [cs:w_seg]
        mov     di, [cs:w_off]
        mov     dx, [cs:r_port]
.next:  mov     ax, bp
        mov     cl, 4
        shr     ax, cl                  ; BANK = sector >> 4 (bit 7 selects the chip)
        mov     si, bp
        and     si, SECTORS_PER_BANK - 1
        mov     cl, 9
        shl     si, cl
        mov     ds, [cs:r_winseg]
        mov     cx, SECTOR_SIZE / 2
        cli
        out     dx, al
.cp:    lodsw
        not     ax                      ; stored inverted
        stosw
        loop    .cp
        xor     al, al
        out     dx, al                  ; bank 0 again
        sti
        mov     ax, es
        add     ax, SECTOR_SIZE / 16
        mov     es, ax
        sub     di, SECTOR_SIZE
        inc     bp
        inc     byte [cs:t_done]
        dec     byte [cs:t_left]
        jnz     .next
i13_done:
        pop     bp
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        mov     al, [cs:t_done]
        xor     ah, ah
        mov     [cs:r_status], ah
        clc
        retf    2

i13_badsec:
        mov     ah, 04h                 ; sector not found
i13_fail:
        pop     bp
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        mov     al, [cs:t_done]
        jmp     i13_err

; AH=03h: write. Needs the WRITE jumper JP1; without it VPP is low and the result is AH=03h
; (write protected) before anything changes.
i13_write:
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    ds
        push    es
        push    bp
        call    chs_lin
        jc      i13_badsec
        call    norm_buf
        mov     dx, [cs:r_port]
        inc     dx
        mov     al, CTRL_WE_EN | CTRL_VPP_EN
        out     dx, al
        dec     dx
        mov     cx, 2
        call    wait_ticks              ; VPP settles
.blk:   mov     ax, bp                  ; k = sectors of the request in this 64 KB block
        and     ax, SECTORS_PER_BLOCK - 1
        mov     cx, SECTORS_PER_BLOCK
        sub     cx, ax
        mov     al, [cs:t_left]
        xor     ah, ah
        cmp     cx, ax
        jbe     .k
        mov     cx, ax
.k:     mov     [cs:w_k], cx
        call    fits_inplace
        jc      .rewrite
        call    prog_inplace
        jmp     .chk
.rewrite:
        call    rewrite_block
.chk:   jc      .fail
        mov     ax, [cs:w_k]
        add     bp, ax
        add     [cs:t_done], al
        sub     [cs:t_left], al
        mov     cl, 5
        shl     ax, cl                  ; sectors -> paragraphs
        add     [cs:w_seg], ax
        cmp     byte [cs:t_left], 0
        jne     .blk
        call    wr_off
        jmp     i13_done
.fail:  call    wr_off
        jmp     i13_fail

; ---- write helpers. DX = port, BP = first sector of the request part, w_k = its length ----
wr_off: push    ax
        push    dx
        mov     dx, [cs:r_port]
        xor     al, al
        out     dx, al                  ; BANK = 0
        inc     dx
        out     dx, al                  ; CTRL = 0
        pop     dx
        pop     ax
        ret

wait_ticks:                             ; CX timer ticks
        push    ax
        push    bx
        push    ds
        xor     ax, ax
        mov     ds, ax
        sti
        mov     bx, [46Ch]
.w:     mov     ax, [46Ch]
        sub     ax, bx
        cmp     ax, cx
        jb      .w
        pop     ds
        pop     bx
        pop     ax
        ret

; sec_addr: BP = sector -> bank selected (interrupts off), DI = offset in the window
sec_addr:
        mov     ax, bp
        mov     cl, 4
        shr     ax, cl
        cli
        out     dx, al
        mov     di, bp
        and     di, SECTORS_PER_BANK - 1
        mov     cl, 9
        shl     di, cl
        ret

bank0:  push    ax
        xor     al, al
        out     dx, al
        sti
        pop     ax
        ret

; fits_inplace: CF = some new byte needs a 0 -> 1 change of a stored bit, i.e. an erase
fits_inplace:
        push    bp
        mov     ds, [cs:w_seg]
        mov     si, [cs:w_off]
        mov     es, [cs:r_winseg]
        mov     bx, [cs:w_k]
.sec:   call    sec_addr
        mov     cx, SECTOR_SIZE
.b:     lodsb
        not     al                      ; value to store
        mov     ah, [es:di]
        inc     di
        and     ah, al
        cmp     ah, al
        jne     .no
        loop    .b
        call    bank0
        mov     ax, ds
        add     ax, SECTOR_SIZE / 16
        mov     ds, ax
        sub     si, SECTOR_SIZE
        inc     bp
        dec     bx
        jnz     .sec
        pop     bp
        clc
        ret
.no:    call    bank0
        pop     bp
        stc
        ret

; prog_inplace: program the bytes that differ (only 1 -> 0 changes are left, fits_inplace checked)
prog_inplace:
        push    bp
        mov     ds, [cs:w_seg]
        mov     si, [cs:w_off]
        mov     es, [cs:r_winseg]
        mov     bx, [cs:w_k]
.sec:   call    sec_addr
        mov     cx, SECTOR_SIZE
.b:     lodsb
        not     al
        cmp     al, [es:di]
        je      .same
        call    prog_byte
        jc      .err
.same:  inc     di
        loop    .b
        call    bank0
        mov     ax, ds
        add     ax, SECTOR_SIZE / 16
        mov     ds, ax
        sub     si, SECTOR_SIZE
        inc     bp
        dec     bx
        jnz     .sec
        pop     bp
        clc
        ret
.err:   call    bank0
        pop     bp
        stc
        ret

; prog_byte: ES:DI (bank selected) <- AL, then back to Read Array. CF = error, AH = BIOS error code.
prog_byte:
        push    cx
        mov     byte [es:di], FL_PROGRAM
        mov     [es:di], al
        mov     cx, 0FFFFh
.w:     mov     ah, [es:di]
        test    ah, SR_READY
        jnz     .done
        loop    .w
        mov     ah, 80h                 ; timeout
        jmp     .bad
.done:  test    ah, SR_VPP_LOW | SR_PROG_ERR
        jnz     .st
        mov     byte [es:di], FL_READ_ARRAY
        pop     cx
        clc
        ret
.st:    test    ah, SR_VPP_LOW
        mov     ah, 03h                 ; VPP low: JP1 open, write protected
        jnz     .bad
        mov     ah, 0BBh
.bad:   mov     byte [es:di], FL_CLEAR_STATUS
        mov     byte [es:di], FL_READ_ARRAY
        pop     cx
        stc
        ret

; erase_blk: AL = 64 KB block -> erased. Interrupts on while waiting. CF = error, AH = BIOS error code.
erase_blk:
        push    cx
        push    di
        mov     cl, 3
        shl     al, cl
        out     dx, al
        mov     es, [cs:r_winseg]
        xor     di, di
        mov     byte [es:di], FL_CLEAR_STATUS
        mov     byte [es:di], FL_ERASE_SETUP
        mov     byte [es:di], FL_CONFIRM
        sti
        push    ds
        xor     cx, cx
        mov     ds, cx
        mov     cx, [46Ch]
        pop     ds
        mov     [cs:w_t0], cx
.w:     mov     ah, [es:di]
        test    ah, SR_READY
        jnz     .done
        push    ds
        xor     cx, cx
        mov     ds, cx
        mov     cx, [46Ch]
        pop     ds
        sub     cx, [cs:w_t0]
        cmp     cx, TICKS_ERASE
        jb      .w
        mov     ah, 80h
        jmp     .bad
.done:  test    ah, SR_VPP_LOW | SR_ERASE_ERR | SR_PROG_ERR
        jnz     .st
        mov     byte [es:di], FL_READ_ARRAY
        pop     di
        pop     cx
        clc
        ret
.st:    test    ah, SR_VPP_LOW
        mov     ah, 03h
        jnz     .bad
        mov     ah, 0BBh
.bad:   mov     byte [es:di], FL_CLEAR_STATUS
        mov     byte [es:di], FL_READ_ARRAY
        pop     di
        pop     cx
        stc
        ret

; read_rbuf: AX = sector -> its stored bytes in rbuf
read_rbuf:
        push    cx
        push    si
        push    di
        push    ds
        push    es
        push    ax
        mov     cl, 4
        shr     ax, cl
        cli
        out     dx, al
        pop     ax
        mov     si, ax
        and     si, SECTORS_PER_BANK - 1
        mov     cl, 9
        shl     si, cl
        mov     ds, [cs:r_winseg]
        push    cs
        pop     es
        mov     di, rbuf
        mov     cx, SECTOR_SIZE / 2
        rep     movsw
        xor     al, al
        out     dx, al
        sti
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     cx
        ret

; prog_erased: AX = erased sector <- DS:SI (XOR w_inv), only bytes that are not FFh. CF = error, AH = code.
prog_erased:
        push    cx
        push    di
        push    es
        mov     es, [cs:r_winseg]
        push    ax
        mov     cl, 4
        shr     ax, cl
        cli
        out     dx, al
        pop     ax
        mov     di, ax
        and     di, SECTORS_PER_BANK - 1
        mov     cl, 9
        shl     di, cl
        mov     cx, SECTOR_SIZE
.b:     lodsb
        xor     al, [cs:w_inv]
        cmp     al, 0FFh
        je      .skip
        call    prog_byte
        jc      .err
.skip:  inc     di
        loop    .b
        call    bank0
        pop     es
        pop     di
        pop     cx
        clc
        ret
.err:   call    bank0
        pop     es
        pop     di
        pop     cx
        stc
        ret

; rewrite_block: the request part needs an erase. Spare <- erase; spare <- block with the new sectors merged;
; block <- erase; block <- spare. A power failure between the second erase and the end loses the block
; (the spare still holds it, but nothing restores it automatically in this version).
rewrite_block:
        push    bp
        mov     ax, bp
        mov     cl, 7
        shr     ax, cl
        mov     [cs:w_blk], al
        mov     al, [cs:r_spare]
        call    erase_blk
        jc      .err
        xor     bx, bx
.c1:    mov     al, [cs:w_blk]
        call    blk_sector
        mov     [cs:w_src], ax
        mov     al, [cs:r_spare]
        call    blk_sector
        mov     [cs:w_dst], ax
        mov     ax, [cs:w_src]
        sub     ax, bp
        jb      .old
        cmp     ax, [cs:w_k]
        jae     .old
        mov     cl, 5                   ; new data: caller sector AX
        shl     ax, cl
        add     ax, [cs:w_seg]
        mov     ds, ax
        mov     si, [cs:w_off]
        mov     byte [cs:w_inv], 0FFh
        jmp     .prog
.old:   mov     ax, [cs:w_src]
        call    read_rbuf
        push    cs
        pop     ds
        mov     si, rbuf
        mov     byte [cs:w_inv], 0
.prog:  mov     ax, [cs:w_dst]
        call    prog_erased
        jc      .err
        inc     bx
        cmp     bx, SECTORS_PER_BLOCK
        jb      .c1

        mov     al, [cs:w_blk]
        call    erase_blk
        jc      .err
        xor     bx, bx
        mov     byte [cs:w_inv], 0
.c2:    mov     al, [cs:r_spare]
        call    blk_sector
        call    read_rbuf
        push    cs
        pop     ds
        mov     si, rbuf
        mov     al, [cs:w_blk]
        call    blk_sector
        call    prog_erased
        jc      .err
        inc     bx
        cmp     bx, SECTORS_PER_BLOCK
        jb      .c2
        pop     bp
        clc
        ret
.err:   pop     bp
        stc
        ret

blk_sector:                             ; AL = block, BX = sector in block -> AX = sector
        push    cx
        xor     ah, ah
        mov     cl, 7
        shl     ax, cl
        add     ax, bx
        pop     cx
        ret

; ---- INT 19h: A: first, then the flash disk, then the original bootstrap ----
int19:  sti
        xor     ax, ax
        mov     ds, ax
        mov     es, ax
        mov     di, 4
.floppy:
        xor     ax, ax
        xor     dx, dx
        int     13h
        mov     ax, 0201h
        mov     bx, 7C00h
        mov     cx, 0001h
        xor     dx, dx
        int     13h
        jnc     .boot_a
        dec     di
        jnz     .floppy
        mov     ax, 0201h
        mov     bx, 7C00h
        mov     cx, 0001h
        mov     dx, 0080h
        int     13h
        jc      .chain
        cmp     word [7DFEh], 0AA55h
        jne     .chain
        mov     dx, 0080h
        jmp     0:7C00h
.boot_a:
        xor     dx, dx
        jmp     0:7C00h
.chain: jmp     far [cs:r_old19]

; ---- resident data ----
desc_sig:       db      'ISAFLDSK'
r_port          dw      0
r_winseg        dw      0
r_cyls          dw      0
r_heads         dw      0
r_spt           dw      0
r_total         dw      0
r_data          dw      0
r_old13         dd      0
r_old19         dd      0
w_seg           dw      0
w_off           dw      0
w_k             dw      0
w_src           dw      0
w_dst           dw      0
w_t0            dw      0
r_drive         db      0
r_status        db      0
r_valid         db      0
r_spare         db      0
t_left          db      0
t_done          db      0
t_sec           db      0
t_head          db      0
w_blk           db      0
w_inv           db      0
rbuf:           times SECTOR_SIZE db 0
res_end:

res_size equ    res_end - res_begin
%if res_size > RES_KB * 1024
%error resident part does not fit into RES_KB
%endif

; =====================================================================================================
        section tail start=ROM_SIZE-1
        db      0                       ; checksum, fixed by tools/build_dos.py and by FLFORMAT
