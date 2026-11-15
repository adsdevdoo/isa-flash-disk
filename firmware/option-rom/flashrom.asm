; ISA Flash Disk option ROM (8 KB, lives in flash bank 0 of chip U1).
;
; Build:  nasm -f bin -I ../include/ -o FLASHROM.BIN flashrom.asm   (tools/build_dos.py also fixes the checksum)
;
; The BIOS finds the ROM in the 8 KB window (XT Technical Reference 5-10) and far-calls offset 3.
; init runs from the window: it takes 3 KB from the top of base memory (word 40h:13h) and copies the
; resident part there. Only the resident part may switch banks, because the ROM disappears from the window
; as soon as another bank is selected: init far-calls the RAM copy of read_desc to fetch the descriptor
; from bank 1 and the block map from the block headers (disk format 3, docs/programming.md), then installs
; an INT 13h hard disk (read and write) and, when the disk became 80h, an INT 19h handler that boots from A:
; first and from the flash disk next.
;
; Bank 0 rule (docs/architecture.md): every routine leaves BANK = 0 and CTRL = 0 with interrupts enabled,
; so a warm boot (Ctrl-Alt-Del does not pulse RESET DRV) still finds this ROM.

        cpu     8086
        bits    16

%include "isaflash.inc"

RES_KB  equ     3                       ; resident part size in KB taken from base memory
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
        db      1, 2                    ; ROMH_VERSION
        db      'ISA Flash Disk option ROM 1.2', 0

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
.back:  cmp     byte [es:r_valid], 2
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

.bad:   mov     bl, [es:r_valid]
        mov     ax, 40h
        mov     ds, ax
        add     word [13h], RES_KB      ; give the memory back
        push    cs
        pop     ds
        mov     si, msg_head
        call    print
        mov     si, msg_nodisk
        cmp     bl, 1
        jne     .msg
        mov     si, msg_nomap
.msg:   call    print
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
msg_nodisk:     db      'no disk (format 3), run FLFORMAT /E', 13, 10, 0
msg_nomap:      db      'disk block map damaged, run FLFORMAT /E', 13, 10, 0

res_load equ    section.res.start

; =====================================================================================================
        section res vstart=0 follows=.text align=16
res_begin:

; ---- read_desc: far-called by init and by the remount call. Descriptor fields from bank 1, then the block map.
; r_valid: 0 = no format 3 descriptor, 1 = descriptor but no complete block map, 2 = disk ready.
read_desc:
        push    ax
        push    bx
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
        mov     al, [es:DESC_LBLKS]
        mov     [r_nl], al
        mov     al, [es:DESC_PBLKS]
        mov     [r_np], al
        mov     ax, [es:DESC_BAD]
        mov     [r_bad], ax
        mov     ax, [es:DESC_BAD + 2]
        mov     [r_bad + 2], ax
        mov     byte [r_valid], 1
.out:   xor     al, al
        out     dx, al                  ; bank 0: the ROM is back
        sti
        cmp     byte [r_valid], 1
        jne     .ret
        call    mount
.ret:   pop     es
        pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        retf

; mount: reads the header of every physical block (1..r_np) and keeps, for each logical block, the complete
; copy with the highest generation. r_free = the physical block left over, r_seq = highest generation seen.
; r_valid = 2 when every logical block has a copy. DS = CS, DX = port. Uses rbuf for the generations.
mount:
        push    cs
        pop     es
        mov     al, [r_nl]
        or      al, al
        jz      .ret
        cmp     al, [r_np]
        jae     .ret
        cmp     byte [r_np], 31
        ja      .ret
        mov     ah, SECTORS_PER_LBLK
        mul     ah
        cmp     ax, [r_total]
        jb      .ret
        mov     di, r_map
        mov     cx, 32
        mov     al, 0FFh
        rep     stosb
        xor     ax, ax
        mov     [r_seq], ax
        mov     [r_seq + 2], ax
        mov     byte [m_p], 1
.blk:   mov     al, [m_p]
        call    is_bad
        jnz     .next
        mov     cl, 3
        shl     al, cl
        add     al, HDR_BANK
        mov     si, HDR_WOFF
        mov     ds, [cs:r_winseg]
        cli
        out     dx, al
        cmp     word [si + HDR_SIG], 'FL'
        jne     .bad
        cmp     word [si + HDR_SIG + 2], 'BK'
        jne     .bad
        mov     bl, [si + HDR_LBLK]
        mov     bh, [si + HDR_LBLK + 1]
        not     bh
        cmp     bl, bh
        jne     .bad
        mov     ax, [si + HDR_GEN + 4]
        not     ax
        cmp     ax, [si + HDR_GEN]
        jne     .bad
        mov     cx, [si + HDR_GEN + 6]
        not     cx
        cmp     cx, [si + HDR_GEN + 2]
        jne     .bad
        cmp     byte [si + HDR_VALID], 0
        jne     .bad
        call    bank0                   ; complete copy: BL = logical block, CX:AX = generation
        push    cs
        pop     ds
        cmp     bl, [r_nl]
        jae     .next
        cmp     cx, [r_seq + 2]
        jb      .cand
        ja      .max
        cmp     ax, [r_seq]
        jbe     .cand
.max:   mov     [r_seq], ax
        mov     [r_seq + 2], cx
.cand:  xor     bh, bh
        mov     di, bx
        shl     di, 1
        shl     di, 1                   ; generation of logical block BX at rbuf + 4 * BX
        cmp     byte [r_map + bx], 0FFh
        je      .take
        cmp     cx, [rbuf + di + 2]
        jb      .next
        ja      .take
        cmp     ax, [rbuf + di]
        jbe     .next
.take:  mov     [rbuf + di], ax
        mov     [rbuf + di + 2], cx
        mov     al, [m_p]
        mov     [r_map + bx], al
        jmp     .next
.bad:   call    bank0
        push    cs
        pop     ds
.next:  inc     byte [m_p]
        mov     al, [m_p]
        cmp     al, [r_np]
        jbe     .blk

        xor     bx, bx                  ; every logical block needs a copy
.chk:   cmp     byte [r_map + bx], 0FFh
        je      .ret
        inc     bx
        cmp     bl, [r_nl]
        jb      .chk
        mov     al, 1                   ; free block = first physical block that holds no logical one
.fr:    call    is_bad
        jnz     .frn
        mov     di, r_map
        mov     cl, [r_nl]
        xor     ch, ch
        repne   scasb
        jne     .free
.frn:   inc     al
        cmp     al, [r_np]
        jbe     .fr
        jmp     .ret
.free:  mov     [r_free], al
        mov     al, [r_seq]             ; round-robin start for the wear leveling moves
        xor     ah, ah
        div     byte [r_nl]
        mov     [r_rr], ah
        mov     byte [r_valid], 2
.ret:   ret

; is_bad: AL = flash block -> ZF = 0 when the descriptor marks it bad. Keeps all registers.
is_bad: push    ax
        push    bx
        push    cx
        mov     cl, al
        and     cl, 15
        mov     bx, 1
        shl     bx, cl
        test    al, 16
        jnz     .hi
        test    [cs:r_bad], bx
        jmp     .out
.hi:    test    [cs:r_bad + 2], bx
.out:   pop     cx
        pop     bx
        pop     ax
        ret

; ---- INT 13h: hard disk, disk format 3 (docs/programming.md) ----
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
        cmp     ah, INT13_REMOUNT
        je      i13_remount
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
i13_inval:
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

; AH=F1h, BX=464Ch (private, used by FLWRITE and FLFORMAT after they changed the flash): read the descriptor
; and the block map again. BX = 6C66h on return.
i13_remount:
        cmp     bx, REMOUNT_KEY
        jne     i13_inval
        push    cs
        call    read_desc
        mov     bx, REMOUNT_ACK
        cmp     byte [cs:r_valid], 2
        je      i13_ok
        mov     ah, 0AAh                ; drive not ready
        jmp     i13_err

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

; chs_lin: AL = count, CH/CL/DH = C/H/S (BIOS packing) -> BP = logical sector (LBA), t_left = count.
; CF = outside the disk or no disk. Destroys AX, CX, DX.
chs_lin:
        mov     [cs:t_left], al
        mov     byte [cs:t_done], 0
        cmp     byte [cs:r_valid], 2
        jne     .bad
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
        mov     bp, ax
        clc
        ret
.bad:   stc
        ret

; lba2phys: AX = logical sector -> AX = linear sector on the card (block from the map). Keeps other registers.
lba2phys:
        push    bx
        push    cx
        push    dx
        xor     dx, dx
        mov     cx, SECTORS_PER_LBLK
        div     cx                      ; AX = logical block, DX = sector in it
        mov     bx, ax
        mov     al, [cs:r_map + bx]
        xor     ah, ah
        mov     cl, 7
        shl     ax, cl
        add     ax, dx
        pop     dx
        pop     cx
        pop     bx
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
        call    lba2phys
        mov     si, ax
        mov     cl, 4
        shr     ax, cl                  ; BANK = sector >> 4 (bit 7 selects the chip)
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
.blk:   push    dx                      ; part = sectors of the request inside one logical block
        mov     ax, bp
        xor     dx, dx
        mov     cx, SECTORS_PER_LBLK
        div     cx
        mov     [cs:w_l], al
        mov     [cs:w_s], dx
        sub     cx, dx
        pop     dx
        mov     al, [cs:t_left]
        xor     ah, ah
        cmp     cx, ax
        jbe     .k
        mov     cx, ax
.k:     mov     [cs:w_k], cx
        push    bp
        mov     ax, bp
        call    lba2phys
        mov     bp, ax                  ; physical sector of the part (contiguous inside the block)
        call    fits_inplace
        jc      .rewrite
        call    prog_inplace
        jmp     .chk
.rewrite:
        call    rewrite
.chk:   pop     bp
        jc      .fail
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

; ---- write helpers. DX = port, BP = first physical sector of the request part, w_k = its length ----
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

; rewrite: the request part needs an erase. Moves logical block w_l into the free block with the new sectors
; merged; every 8th generation one more block moves, round-robin (wear leveling). CF = error, AH = BIOS code.
rewrite:
        call    move_block
        jc      .ret
        test    byte [cs:r_seq], RELOC_MASK
        jnz     .ok
        push    word [cs:w_k]
        mov     al, [cs:w_l]
        push    ax
        mov     al, [cs:r_rr]
        mov     [cs:w_l], al
        inc     al
        cmp     al, [cs:r_nl]
        jb      .rr
        xor     al, al
.rr:    mov     [cs:r_rr], al
        mov     word [cs:w_k], 0
        call    move_block
        pop     ax                      ; flags stay from move_block
        mov     [cs:w_l], al
        pop     word [cs:w_k]
        ret
.ok:    clc
.ret:   ret

; move_block: logical block w_l -> the free block. Sectors w_s .. w_s+w_k-1 come from the caller's buffer
; (w_seg:w_off), the others from the current copy. The header with the next generation is written last, so
; a power failure before it leaves the old copy in force; after it the new copy wins (higher generation).
; The old copy becomes the free block. CF = error, AH = BIOS code.
move_block:
        push    bx
        xor     bx, bx
        mov     bl, [cs:w_l]
        mov     al, [cs:r_map + bx]
        mov     [cs:w_src], al
        mov     al, [cs:r_free]
        mov     [cs:w_dst], al
        call    erase_blk
        jc      .err
        xor     bx, bx
.sec:   mov     ax, bx
        sub     ax, [cs:w_s]
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
.old:   mov     al, [cs:w_src]
        call    blk_sector
        call    read_rbuf
        push    cs
        pop     ds
        mov     si, rbuf
        mov     byte [cs:w_inv], 0
.prog:  mov     al, [cs:w_dst]
        call    blk_sector
        call    prog_erased
        jc      .err
        inc     bx
        cmp     bx, SECTORS_PER_LBLK
        jb      .sec
        call    write_hdr
        jc      .err
        xor     bx, bx
        mov     bl, [cs:w_l]
        mov     al, [cs:w_dst]
        mov     [cs:r_map + bx], al
        mov     al, [cs:w_src]
        mov     [cs:r_free], al
        pop     bx
        clc
        ret
.err:   pop     bx
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

; write_hdr: header of block w_dst for logical block w_l with generation r_seq + 1, VALID byte last.
; CF = error, AH = BIOS code.
write_hdr:
        push    cx
        push    si
        push    di
        push    es
        add     word [cs:r_seq], 1
        adc     word [cs:r_seq + 2], 0
        mov     al, [cs:w_l]
        mov     [cs:hdr + HDR_LBLK], al
        not     al
        mov     [cs:hdr + HDR_LBLK + 1], al
        mov     ax, [cs:r_seq]
        mov     [cs:hdr + HDR_GEN], ax
        not     ax
        mov     [cs:hdr + HDR_GEN + 4], ax
        mov     ax, [cs:r_seq + 2]
        mov     [cs:hdr + HDR_GEN + 2], ax
        not     ax
        mov     [cs:hdr + HDR_GEN + 6], ax
        mov     al, [cs:w_dst]
        mov     cl, 3
        shl     al, cl
        add     al, HDR_BANK
        mov     es, [cs:r_winseg]
        cli
        out     dx, al
        mov     di, HDR_WOFF
        mov     si, hdr
        mov     cx, HDR_LEN
.b:     mov     al, [cs:si]
        inc     si
        cmp     al, 0FFh
        je      .skip
        call    prog_byte
        jc      .err
.skip:  inc     di
        loop    .b
        call    bank0
        pop     es
        pop     di
        pop     si
        pop     cx
        clc
        ret
.err:   call    bank0
        pop     es
        pop     di
        pop     si
        pop     cx
        stc
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
hdr:            db      'FLBK', 0FFh, 0FFh, 0FFh, 0FFh  ; block header image (HDR_*), VALID = 0 is the last byte
                times 8 db 0FFh
                db      0
r_port          dw      0
r_winseg        dw      0
r_cyls          dw      0
r_heads         dw      0
r_spt           dw      0
r_total         dw      0
r_seq           dd      0
r_bad           dd      0
r_old13         dd      0
r_old19         dd      0
w_seg           dw      0
w_off           dw      0
w_k             dw      0
w_s             dw      0
w_t0            dw      0
r_drive         db      0
r_status        db      0
r_valid         db      0
r_nl            db      0
r_np            db      0
r_free          db      0
r_rr            db      0
m_p             db      0
t_left          db      0
t_done          db      0
t_sec           db      0
t_head          db      0
w_l             db      0
w_src           db      0
w_dst           db      0
w_inv           db      0
r_map:          times 32 db 0FFh
rbuf:           times SECTOR_SIZE db 0
res_end:

res_size equ    res_end - res_begin
%if res_size > RES_KB * 1024
%error resident part does not fit into RES_KB
%endif

; =====================================================================================================
        section tail start=ROM_SIZE-1
        db      0                       ; checksum, fixed by tools/build_dos.py and by FLFORMAT
