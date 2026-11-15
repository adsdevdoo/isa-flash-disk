; ISA Flash Disk option ROM (8 KB, lives in flash bank 0 of chip U1).
;
; Build:  nasm -f bin -I ../include/ -o FLASHROM.BIN flashrom.asm   (tools/build_dos.py also fixes the checksum)
;
; The BIOS finds the ROM in the 8 KB window (XT Technical Reference 5-10) and far-calls offset 3.
; init runs from the window: it takes 1 KB from the top of base memory (word 40h:13h) and copies the
; resident part there. Only the resident part may switch banks, because the ROM disappears from the window
; as soon as another bank is selected: init far-calls the RAM copy of read_desc to fetch the descriptor
; from bank 1, then validates it, installs a read-only INT 13h hard disk and, when the disk became drive 80h,
; an INT 19h handler that boots from A: first and from the flash disk next.
;
; Bank 0 rule (docs/architecture.md): every routine leaves BANK = 0 and CTRL = 0 with interrupts enabled,
; so a warm boot (Ctrl-Alt-Del does not pulse RESET DRV) still finds this ROM.

        cpu     8086
        bits    16

%include "isaflash.inc"

RES_KB  equ     1                       ; resident part size in KB taken from base memory

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
        db      1, 0                    ; ROMH_VERSION
        db      'ISA Flash Disk option ROM 1.0', 0

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

; ---- INT 13h: read-only hard disk ----
int13:
        cmp     dl, [cs:r_drive]
        je      .ours
        jmp     far [cs:r_old13]
.ours:  sti
        cld
        cmp     ah, 02h
        je      i13_read
        cmp     ah, 08h
        je      i13_params
        cmp     ah, 15h
        je      i13_type
        cmp     ah, 01h
        je      i13_status
        cmp     ah, 03h                 ; write
        je      i13_wp
        cmp     ah, 05h                 ; format
        je      i13_wp
        cmp     ah, 00h                 ; reset
        je      i13_ok
        cmp     ah, 04h                 ; verify
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
i13_wp: mov     ah, 03h                 ; write protected
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

; AH=02h: AL = count, CH = cylinder bits 7..0, CL = sector | cylinder bits 9..8, DH = head, ES:BX = buffer
i13_read:
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    ds
        push    es
        push    bp
        mov     [cs:t_left], al
        mov     byte [cs:t_done], 0
        or      al, al
        jz      .badsec
        mov     al, cl
        and     al, 3Fh
        jz      .badsec
        cmp     al, [cs:r_spt]
        ja      .badsec
        mov     [cs:t_sec], al
        cmp     dh, [cs:r_heads]
        jae     .badsec
        mov     [cs:t_head], dh
        mov     al, ch
        mov     ah, cl
        mov     cl, 6
        shr     ah, cl                  ; AX = cylinder
        cmp     ax, [cs:r_cyls]
        jae     .badsec
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
        ja      .badsec
        add     ax, [cs:r_data]         ; linear sector number on the card
        mov     bp, ax

        mov     di, bx                  ; normalise ES:DI, so 512-byte copies never wrap
        mov     ax, di
        mov     cl, 4
        shr     ax, cl
        mov     cx, es
        add     ax, cx
        mov     es, ax
        and     di, 0Fh
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
        rep     movsw
        xor     al, al
        out     dx, al                  ; bank 0 again
        sti
        mov     ax, es                  ; next 512 bytes of the buffer
        add     ax, SECTOR_SIZE / 16
        mov     es, ax
        sub     di, SECTOR_SIZE
        inc     bp
        inc     byte [cs:t_done]
        dec     byte [cs:t_left]
        jnz     .next

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

.badsec:
        pop     bp
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        mov     al, [cs:t_done]
        mov     ah, 04h                 ; sector not found
        jmp     i13_err

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
r_drive         db      0
r_status        db      0
r_valid         db      0
t_left          db      0
t_done          db      0
t_sec           db      0
t_head          db      0
res_end:

res_size equ    res_end - res_begin
%if res_size > RES_KB * 1024
%error resident part does not fit into RES_KB
%endif

; =====================================================================================================
        section tail start=ROM_SIZE-1
        db      0                       ; checksum, fixed by tools/build_dos.py and by FLFORMAT
