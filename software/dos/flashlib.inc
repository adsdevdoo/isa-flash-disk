; flashlib.inc - ISA Flash Disk card access for the .COM utilities (8086, tiny model, DS = CS).
; Card: docs/architecture.md, docs/memory-map.md. Flash algorithms: 28F008SA datasheet 290429-008, fig. 6 and 8.
; Every exit path calls card_safe: Read Array, CTRL = 0 (no WE#, no VPP), BANK = 0 (bank 0 rule).

TICKS_ERASE     equ     400             ; 22 s; datasheet maximum block erase time is 10 s (DS p. 34)
TICKS_VPP       equ     2               ; settle time after switching VPP on

; ---- registers ----
set_bank:                               ; AL
        push    dx
        mov     dx, [port]
        out     dx, al
        pop     dx
        ret

set_ctrl:                               ; AL
        push    dx
        mov     dx, [port]
        inc     dx
        out     dx, al
        pop     dx
        ret

; card_safe: flash back to Read Array, no write enable, no VPP, bank 0. Safe to call at any time.
card_safe:
        push    ax
        push    es
        cmp     byte [card_ok], 0
        je      .regs
        mov     es, [winseg]
        mov     al, CTRL_WE_EN
        call    set_ctrl
        xor     al, al
        call    set_bank
        mov     byte [es:0], FL_READ_ARRAY
        cmp     byte [chips], 2
        jb      .regs
        mov     al, 80h
        call    set_bank
        mov     byte [es:0], FL_READ_ARRAY
.regs:  cmp     word [port], 0
        je      .end
        xor     al, al
        call    set_ctrl
        call    set_bank
.end:   pop     es
        pop     ax
        ret

; Ctrl-Break / Ctrl-C: make the card safe, then end the program
break_handler:
        push    cs
        pop     ds
        mov     al, 3
        jmp     exit_prog

install_break:
        mov     dx, break_handler
        mov     ax, 2523h
        int     21h
        ret

; ---- finding the card ----
; card_find: window from /M or from the ROM signature scan (C800h..F400h), port from /P, the ROM header or 2A0h.
; Then reads the chip IDs. CF = no 28F008SA found.
card_find:
        push    es
        mov     ax, [opt_mem]
        or      ax, ax
        jz      .scan
        mov     [winseg], ax
        call    rom_sig_at
        jmp     .port
.scan:  mov     ax, WINDOW_FIRST
.s1:    call    rom_sig_at
        jnc     .found
        add     ax, WINDOW_SIZE / 16
        cmp     ax, WINDOW_LAST
        jbe     .s1
        mov     word [winseg], DEFAULT_WINDOW
        jmp     .port
.found: mov     [winseg], ax
.port:  mov     ax, [opt_port]
        or      ax, ax
        jnz     .setp
        mov     ax, DEFAULT_PORT
        cmp     byte [rom_found], 0
        je      .setp
        mov     es, [winseg]
        mov     ax, [es:ROMH_PORT]
.setp:  mov     [port], ax
        mov     byte [card_ok], 0
        call    card_safe
        xor     al, al
        call    read_id
        cmp     ax, FL_DEV_28F008SA * 256 + FL_MFR_INTEL
        jne     .none
        mov     byte [chips], 1
        mov     byte [card_ok], 1
        mov     al, 1
        call    read_id
        mov     [id1], ax
        cmp     ax, FL_DEV_28F008SA * 256 + FL_MFR_INTEL
        jne     .one
        mov     byte [chips], 2
.one:   pop     es
        clc
        ret
.none:  mov     [id0], ax
        pop     es
        stc
        ret

; rom_sig_at: AX = segment; CF = no 'ISAFLASH' there. Sets rom_found.
rom_sig_at:
        push    ax
        push    cx
        push    si
        push    di
        push    es
        mov     es, ax
        mov     di, ROMH_SIG
        mov     si, rom_sig
        mov     cx, 8
        repe    cmpsb
        mov     byte [rom_found], 0
        jne     .no
        cmp     word [es:0], 0AA55h
        jne     .no
        mov     byte [rom_found], 1
        pop     es
        pop     di
        pop     si
        pop     cx
        pop     ax
        clc
        ret
.no:    pop     es
        pop     di
        pop     si
        pop     cx
        pop     ax
        stc
        ret

; read_id: AL = chip (0/1) -> AL = manufacturer, AH = device. Needs WE# but not VPP (DS p. 13).
read_id:
        push    cx
        push    es
        mov     cl, 7
        shl     al, cl
        call    set_bank
        mov     al, CTRL_WE_EN
        call    set_ctrl
        mov     es, [winseg]
        mov     byte [es:0], FL_READ_ID
        mov     al, [es:0]
        mov     ah, [es:1]
        mov     byte [es:0], FL_READ_ARRAY
        push    ax
        xor     al, al
        call    set_ctrl
        call    set_bank
        pop     ax
        pop     es
        pop     cx
        ret

; ---- VPP and status ----
vpp_on:
        mov     al, CTRL_WE_EN | CTRL_VPP_EN
        call    set_ctrl
        mov     cx, TICKS_VPP
        jmp     wait_ticks

vpp_off:
        mov     al, CTRL_WE_EN
        jmp     set_ctrl

wait_ticks:                             ; CX ticks (55 ms)
        push    ax
        push    bx
        push    es
        xor     ax, ax
        mov     es, ax
        mov     bx, [es:46Ch]
.w:     mov     ax, [es:46Ch]
        sub     ax, bx
        cmp     ax, cx
        jb      .w
        pop     es
        pop     bx
        pop     ax
        ret

; wait_ready: ES:DI in status mode, CX = timeout ticks -> AL = status. CF = timeout.
wait_ready:
        push    bx
        push    dx
        push    ds
        xor     bx, bx
        mov     ds, bx
        mov     bx, [46Ch]
.poll:  mov     al, [es:di]
        test    al, SR_READY
        jnz     .ok
        mov     dx, [46Ch]
        sub     dx, bx
        cmp     dx, cx
        jb      .poll
        pop     ds
        pop     dx
        pop     bx
        stc
        ret
.ok:    pop     ds
        pop     dx
        pop     bx
        clc
        ret

; vpp_test: with VPP switched on, programs FFh over the first ROM byte (no bit can change) and returns the
; status in AL. SR.3 = 1 means VPP is below VPPH: the WRITE jumper JP1 is not fitted.
vpp_test:
        push    cx
        push    di
        push    es
        call    vpp_on
        xor     al, al
        call    set_bank
        mov     es, [winseg]
        xor     di, di
        mov     byte [es:di], FL_CLEAR_STATUS
        mov     byte [es:di], FL_PROGRAM
        mov     byte [es:di], 0FFh
        mov     cx, 5
        call    wait_ready
        push    ax
        mov     byte [es:di], FL_CLEAR_STATUS
        mov     byte [es:di], FL_READ_ARRAY
        pop     ax
        pop     es
        pop     di
        pop     cx
        ret

; ---- erase and program ----
; erase_block: AL = 64 KB block (0..31). VPP must be on. AL = status, CF = error.
erase_block:
        push    cx
        push    di
        push    es
        mov     cl, 3
        shl     al, cl                  ; first bank of the block (bit 7 = chip)
        call    set_bank
        mov     es, [winseg]
        xor     di, di
        mov     byte [es:di], FL_CLEAR_STATUS
        mov     byte [es:di], FL_ERASE_SETUP
        mov     byte [es:di], FL_CONFIRM
        mov     cx, TICKS_ERASE
        call    wait_ready
        jc      .tmo
        mov     byte [es:di], FL_CLEAR_STATUS
        mov     byte [es:di], FL_READ_ARRAY
        test    al, SR_ERASE_ERR | SR_PROG_ERR | SR_VPP_LOW
        jnz     .err
        pop     es
        pop     di
        pop     cx
        clc
        ret
.tmo:   mov     al, 0FFh
.err:   mov     byte [es:di], FL_CLEAR_STATUS
        mov     byte [es:di], FL_READ_ARRAY
        pop     es
        pop     di
        pop     cx
        stc
        ret

; write_block: BL = block (0..31), buffer at [bufseg]:0 (64 KB). VPP must be on.
; Skips identical data, erases only when a bit must go 0 -> 1, programs differing bytes, verifies.
; AL = status on error, CF = error. wb_action = 0 unchanged, 1 programmed, 2 erased and programmed.
write_block:
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    ds
        push    es
        mov     byte [wb_action], 0
        mov     [wb_block], bl
        ; pass 1: compare
        xor     dx, dx                  ; DL = differs, DH = needs erase
        mov     bh, 0                   ; bank index inside the block
.cmp_bank:
        call    wb_select
        mov     ds, [cs:winseg]
        xor     si, si
        mov     es, [cs:bufseg]
        mov     di, bx                  ; buffer offset = bank * 2000h
        mov     di, 0
        mov     al, bh
        mov     ah, 0
        mov     cl, 13
        shl     ax, cl
        mov     di, ax
        mov     cx, WINDOW_SIZE
.cmp:   mov     al, [si]
        mov     ah, [es:di]
        cmp     al, ah
        je      .same
        mov     dl, 1
        and     al, ah
        cmp     al, ah
        je      .same
        mov     dh, 1
.same:  inc     si
        inc     di
        loop    .cmp
        push    cs
        pop     ds
        inc     bh
        cmp     bh, BANKS_PER_BLOCK
        jb      .cmp_bank
        or      dl, dl
        jz      .done
        mov     byte [wb_action], 1
        or      dh, dh
        jz      .prog
        mov     byte [wb_action], 2
        mov     al, [wb_block]
        call    erase_block
        jc      .fail
.prog:  mov     bh, 0
.prog_bank:
        call    wb_select
        ; copy the current bank (Read Array) to tmpbuf, then program the bytes that differ
        push    ds
        mov     ds, [winseg]
        xor     si, si
        push    cs
        pop     es
        mov     di, tmpbuf
        mov     cx, WINDOW_SIZE / 2
        rep     movsw
        pop     ds
        mov     es, [winseg]
        mov     al, bh
        xor     ah, ah
        mov     cl, 13
        shl     ax, cl
        mov     si, ax                  ; buffer offset
        xor     di, di                  ; window offset
.pbyte: push    ds
        mov     ds, [cs:bufseg]
        mov     al, [si]
        pop     ds
        cmp     al, [tmpbuf + di]
        je      .pnext
        mov     byte [es:di], FL_PROGRAM
        mov     [es:di], al
        mov     cx, 0FFFFh
.pwait: mov     ah, [es:di]
        test    ah, SR_READY
        jnz     .pdone
        loop    .pwait
        mov     al, 0FEh                ; program timeout
        jmp     .pfail
.pdone: test    ah, SR_PROG_ERR | SR_VPP_LOW
        jz      .pnext
        mov     al, ah
        jmp     .pfail
.pnext: inc     si
        inc     di
        cmp     di, WINDOW_SIZE
        jb      .pbyte
        mov     byte [es:0], FL_READ_ARRAY
        ; verify this bank
        push    ds
        mov     ds, [bufseg]
        mov     al, bh
        xor     ah, ah
        mov     cl, 13
        shl     ax, cl
        mov     si, ax
        xor     di, di
        mov     cx, WINDOW_SIZE
        repe    cmpsb                   ; DS:SI = buffer, ES:DI = window
        pop     ds
        jne     .vfail
        inc     bh
        cmp     bh, BANKS_PER_BLOCK
        jb      .prog_bank
.done:  call    wb_bank0
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        clc
        ret
.vfail: mov     al, 0FDh                ; verify error
        jmp     .fail
.pfail: mov     byte [es:di], FL_CLEAR_STATUS
        mov     byte [es:di], FL_READ_ARRAY
.fail:  push    ax
        call    wb_bank0
        pop     ax
        pop     es
        pop     ds
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        stc
        ret

wb_select:                              ; bank = block * 8 + BH
        push    ax
        push    cx
        mov     al, [cs:wb_block]
        mov     cl, 3
        shl     al, cl
        add     al, bh
        call    set_bank
        pop     cx
        pop     ax
        ret

wb_bank0:
        push    ax
        xor     al, al
        call    set_bank
        pop     ax
        ret

; ---- disk format 3 (docs/programming.md, firmware/include/isaflash.inc) ----
; load_desc: descriptor (bank 1) -> dbuf, d_nl, d_np. AL = 0 format 3, 1 no descriptor, 2 checksum error,
; 3 another format version (in dbuf). CF unless AL = 0.
load_desc:
        push    cx
        push    si
        push    di
        push    ds
        push    es
        mov     al, DESC_LINEAR / WINDOW_SIZE
        call    set_bank
        mov     ds, [winseg]
        push    cs
        pop     es
        xor     si, si
        mov     di, dbuf
        mov     cx, SECTOR_SIZE / 2
        rep     movsw
        pop     es
        pop     ds
        xor     al, al
        call    set_bank
        push    es
        push    cs
        pop     es
        mov     si, dbuf
        mov     di, desc_sig3
        mov     cx, 8
        repe    cmpsb
        pop     es
        mov     al, 1
        jne     .bad
        mov     si, dbuf
        mov     cx, SECTOR_SIZE
        xor     ah, ah
.sum:   add     ah, [si]
        inc     si
        loop    .sum
        mov     al, 2
        or      ah, ah
        jnz     .bad
        mov     al, 3
        cmp     word [dbuf + DESC_VERSION], DESC_FORMAT
        jne     .bad
        mov     al, [dbuf + DESC_LBLKS]
        mov     [d_nl], al
        mov     al, [dbuf + DESC_PBLKS]
        mov     [d_np], al
        mov     ax, [dbuf + DESC_BAD]
        mov     [d_bad], ax
        mov     ax, [dbuf + DESC_BAD + 2]
        mov     [d_bad + 2], ax
        xor     al, al
        pop     di
        pop     si
        pop     cx
        clc
        ret
.bad:   pop     di
        pop     si
        pop     cx
        stc
        ret

; scan_map: block headers -> fmap (physical block of every logical block: the complete copy with the highest
; generation), fl_free (the physical block left over), fseq (highest generation). Needs load_desc.
; CF = a logical block has no complete copy, or the descriptor counts are wrong.
scan_map:
        push    ax
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    es
        mov     al, [d_nl]
        or      al, al
        jz      .bad
        cmp     al, [d_np]
        jae     .bad
        cmp     byte [d_np], 31
        ja      .bad
        push    cs
        pop     es
        mov     di, fmap
        mov     cx, 32
        mov     al, 0FFh
        rep     stosb
        xor     ax, ax
        mov     [fseq], ax
        mov     [fseq + 2], ax
        mov     byte [sm_p], 1
.blk:   mov     al, [sm_p]
        call    is_bad_d
        jnz     .next
        mov     cl, 3
        shl     al, cl
        add     al, HDR_BANK
        call    set_bank
        mov     es, [winseg]
        mov     si, HDR_WOFF
        cmp     word [es:si + HDR_SIG], 'FL'
        jne     .next
        cmp     word [es:si + HDR_SIG + 2], 'BK'
        jne     .next
        mov     bl, [es:si + HDR_LBLK]
        mov     bh, [es:si + HDR_LBLK + 1]
        not     bh
        cmp     bl, bh
        jne     .next
        cmp     bl, [d_nl]
        jae     .next
        mov     ax, [es:si + HDR_GEN + 4]
        not     ax
        cmp     ax, [es:si + HDR_GEN]
        jne     .next
        mov     dx, [es:si + HDR_GEN + 6]
        not     dx
        cmp     dx, [es:si + HDR_GEN + 2]
        jne     .next
        cmp     byte [es:si + HDR_VALID], 0
        jne     .next
        cmp     dx, [fseq + 2]          ; DX:AX = generation, BL = logical block
        jb      .cand
        ja      .max
        cmp     ax, [fseq]
        jbe     .cand
.max:   mov     [fseq], ax
        mov     [fseq + 2], dx
.cand:  xor     bh, bh
        mov     di, bx
        shl     di, 1
        shl     di, 1
        cmp     byte [fmap + bx], 0FFh
        je      .take
        cmp     dx, [fgen + di + 2]
        jb      .next
        ja      .take
        cmp     ax, [fgen + di]
        jbe     .next
.take:  mov     [fgen + di], ax
        mov     [fgen + di + 2], dx
        mov     al, [sm_p]
        mov     [fmap + bx], al
.next:  inc     byte [sm_p]
        mov     al, [sm_p]
        cmp     al, [d_np]
        jbe     .blk
        xor     al, al
        call    set_bank
        xor     bx, bx
.chk:   cmp     byte [fmap + bx], 0FFh
        je      .bad
        inc     bx
        cmp     bl, [d_nl]
        jb      .chk
        push    cs
        pop     es
        mov     al, 1
.fr:    call    is_bad_d
        jnz     .frn
        mov     di, fmap
        mov     cl, [d_nl]
        xor     ch, ch
        repne   scasb
        jne     .free
.frn:   inc     al
        cmp     al, [d_np]
        jbe     .fr
        jmp     .bad
.free:  mov     [fl_free], al
        pop     es
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        clc
        ret
.bad:   xor     al, al
        call    set_bank
        pop     es
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        stc
        ret

; is_bad_d: AL = flash block -> ZF = 0 when d_bad marks it bad. Keeps all registers.
is_bad_d:
        push    ax
        push    bx
        push    cx
        mov     cl, al
        and     cl, 15
        mov     bx, 1
        shl     bx, cl
        test    al, 16
        jnz     .hi
        test    [d_bad], bx
        jmp     .out
.hi:    test    [d_bad + 2], bx
.out:   pop     cx
        pop     bx
        pop     ax
        ret

; set_bad_d: AL = flash block -> marked bad in d_bad
set_bad_d:
        push    ax
        push    bx
        push    cx
        mov     cl, al
        and     cl, 15
        mov     bx, 1
        shl     bx, cl
        test    al, 16
        jnz     .hi
        or      [d_bad], bx
        jmp     .out
.hi:    or      [d_bad + 2], bx
.out:   pop     cx
        pop     bx
        pop     ax
        ret

; ---- block test (FLTEST, FLFORMAT /E) ----
; test_block: BL = flash block; tb_full = 1 adds the 00h pass. VPP must be on. The block is left erased.
; Erase (timed), every byte FFh?, [program 00h into every byte and verify, erase again (timed), FFh?].
; -> tb_t1, tb_t2 = erase times in timer ticks (tb_t2 = 0 without the 00h pass), AL = 0 good, 1 erase failed,
;    2 not FFh after the erase, 3 00h not programmed or not verified, 4 erase slower than ERASE_BAD_TICKS.
;    CF = AL != 0.
test_block:
        push    bx
        push    cx
        push    di
        push    es
        mov     [tb_blk], bl
        mov     word [tb_t2], 0
        call    tb_erase
        mov     [tb_t1], cx
        jc      .e1
        call    tb_blank
        jc      .e2
        cmp     byte [tb_full], 0
        je      .time
        mov     es, [bufseg]
        xor     di, di
        xor     ax, ax
        mov     cx, 8000h
        rep     stosw
        mov     bl, [tb_blk]
        call    write_block
        jc      .e3
        call    tb_erase
        mov     [tb_t2], cx
        jc      .e1
        call    tb_blank
        jc      .e2
.time:  mov     ax, [tb_t1]
        cmp     ax, [tb_t2]
        jae     .t
        mov     ax, [tb_t2]
.t:     cmp     ax, ERASE_BAD_TICKS
        mov     al, 4
        ja      .err
        xor     al, al
        pop     es
        pop     di
        pop     cx
        pop     bx
        clc
        ret
.e1:    mov     al, 1
        jmp     .err
.e2:    mov     al, 2
        jmp     .err
.e3:    mov     al, 3
.err:   pop     es
        pop     di
        pop     cx
        pop     bx
        stc
        ret

tb_erase:                               ; erase block tb_blk -> CX = timer ticks, CF = error
        push    ax
        push    ds
        xor     cx, cx
        mov     ds, cx
        mov     cx, [46Ch]
        pop     ds
        mov     [tb_start], cx
        mov     al, [tb_blk]
        call    erase_block
        pushf
        push    ds
        xor     cx, cx
        mov     ds, cx
        mov     cx, [46Ch]
        pop     ds
        sub     cx, [tb_start]
        popf
        pop     ax
        ret

tb_blank:                               ; CF = some byte of block tb_blk is not FFh
        push    ax
        push    cx
        push    di
        push    es
        mov     es, [winseg]
        xor     ah, ah
.b:     mov     al, [tb_blk]
        mov     cl, 3
        shl     al, cl
        add     al, ah
        call    set_bank
        xor     di, di
        mov     cx, WINDOW_SIZE
        mov     al, 0FFh
        repe    scasb
        jne     .no
        inc     ah
        cmp     ah, BANKS_PER_BLOCK
        jb      .b
        xor     al, al
        call    set_bank
        pop     es
        pop     di
        pop     cx
        pop     ax
        clc
        ret
.no:    xor     al, al
        call    set_bank
        pop     es
        pop     di
        pop     cx
        pop     ax
        stc
        ret

; test_one: BL = flash block -> test_block and one report line; counts n_good/n_worn/n_bad.
; CF = bad block.
test_one:
        push    ax
        push    dx
        PRINT   msg_tb1
        mov     al, bl
        xor     ah, ah
        call    print_dec
        PRINT   msg_tb2
        call    test_block
        pushf
        push    ax
        mov     ax, [tb_t1]
        call    print_secs
        cmp     byte [tb_full], 0
        je      .one
        PRINT   msg_tb3
        mov     ax, [tb_t2]
        call    print_secs
.one:   PRINT   msg_tb4
        pop     ax
        popf
        jc      .bad
        mov     ax, [tb_t1]
        cmp     ax, [tb_t2]
        jae     .m
        mov     ax, [tb_t2]
.m:     cmp     ax, ERASE_SLOW_TICKS
        ja      .worn
        inc     byte [n_good]
        PRINT   msg_tb_ok
        pop     dx
        pop     ax
        clc
        ret
.worn:  inc     byte [n_worn]
        PRINT   msg_tb_worn
        pop     dx
        pop     ax
        clc
        ret
.bad:   inc     byte [n_bad]
        mov     dx, msg_tb_e1
        cmp     al, 1
        je      .say
        mov     dx, msg_tb_e2
        cmp     al, 2
        je      .say
        mov     dx, msg_tb_e3
        cmp     al, 3
        je      .say
        mov     dx, msg_tb_e4
.say:   call    print_dollar
        pop     dx
        pop     ax
        stc
        ret

; print_secs: AX = timer ticks (55 ms) -> "1.6"
print_secs:
        push    ax
        push    bx
        push    dx
        mov     bx, 11
        mul     bx
        add     ax, 10
        adc     dx, 0
        mov     bx, 20
        div     bx                      ; tenths of a second
        xor     dx, dx
        mov     bx, 10
        div     bx
        mov     bx, dx
        call    print_dec
        mov     dl, '.'
        call    print_char
        mov     dl, bl
        add     dl, '0'
        call    print_char
        pop     dx
        pop     bx
        pop     ax
        ret

; buf_header: AL = logical block -> block header with generation fseq + 1 at [bufseg]:FE00h (fseq += 1).
; The rest of FE00h..FFFFh must be FFh.
buf_header:
        push    ax
        push    di
        push    es
        mov     es, [bufseg]
        mov     di, SECTORS_PER_LBLK * SECTOR_SIZE
        mov     word [es:di + HDR_SIG], 'FL'
        mov     word [es:di + HDR_SIG + 2], 'BK'
        mov     [es:di + HDR_LBLK], al
        not     al
        mov     [es:di + HDR_LBLK + 1], al
        add     word [fseq], 1
        adc     word [fseq + 2], 0
        mov     ax, [fseq]
        mov     [es:di + HDR_GEN], ax
        not     ax
        mov     [es:di + HDR_GEN + 4], ax
        mov     ax, [fseq + 2]
        mov     [es:di + HDR_GEN + 2], ax
        not     ax
        mov     [es:di + HDR_GEN + 6], ax
        mov     byte [es:di + HDR_VALID], 0
        pop     es
        pop     di
        pop     ax
        ret

; remount: tell the resident option ROM (if it is in memory) to read the descriptor and the block map again,
; so it never writes by a block map that the utility has just changed (INT 13h AH=F1h, private).
remount:
        cmp     byte [rom_found], 0
        je      .end
        push    ax
        push    bx
        push    cx
        push    dx
        push    si
        push    di
        push    es
        mov     dl, 80h
.try:   push    dx
        mov     ah, INT13_REMOUNT
        mov     bx, REMOUNT_KEY
        int     13h
        pop     dx
        jc      .nx
        cmp     bx, REMOUNT_ACK
        je      .done
.nx:    inc     dl
        cmp     dl, 84h
        jb      .try
.done:  pop     es
        pop     di
        pop     si
        pop     dx
        pop     cx
        pop     bx
        pop     ax
.end:   ret

desc_sig3:      db      'ISAFLDSK'
msg_tb1:        db      'Block $'
msg_tb2:        db      ': erase $'
msg_tb3:        db      ' s, $'
msg_tb4:        db      ' s  $'
msg_tb_ok:      db      'OK', 13, 10, '$'
msg_tb_worn:    db      'WORN (erase slower than 5 s)', 13, 10, '$'
msg_tb_e1:      db      'BAD (erase failed)', 13, 10, '$'
msg_tb_e2:      db      'BAD (bits stay 0 after the erase)', 13, 10, '$'
msg_tb_e3:      db      'BAD (00h not programmed or not verified)', 13, 10, '$'
msg_tb_e4:      db      'BAD (erase slower than 10 s)', 13, 10, '$'
fseq            dd      0
d_bad           dd      0
tb_t1           dw      0
tb_t2           dw      0
tb_start        dw      0
tb_blk          db      0
tb_full         db      0
n_good          db      0
n_worn          db      0
n_bad           db      0
d_nl            db      0
d_np            db      0
fl_free           db      0
sm_p            db      0
fmap:           times 32 db 0FFh
fgen:           times 32 * 4 db 0
dbuf:           times SECTOR_SIZE db 0

; alloc_buffer: shrink the program to 64 KB and allocate a 64 KB buffer -> [bufseg]. CF = no memory.
alloc_buffer:
        push    es
        push    cs
        pop     es
        mov     bx, 1000h
        mov     ah, 4Ah
        int     21h
        pop     es
        jc      .err
        mov     bx, 1000h
        mov     ah, 48h
        int     21h
        jc      .err
        mov     [bufseg], ax
.err:   ret

; print_card: "Card: window CC00h, port 2A0h, 2 x 28F008SA (2048 KB)"
print_card:
        PRINT   msg_card1
        mov     ax, [winseg]
        call    print_hex16
        PRINT   msg_card2
        mov     ax, [port]
        call    print_hex16
        PRINT   msg_card3
        mov     al, [chips]
        xor     ah, ah
        call    print_dec
        PRINT   msg_card4
        mov     al, [chips]
        xor     ah, ah
        mov     cl, 10
        shl     ax, cl
        call    print_dec
        PRINT   msg_card5
        ret

not_found:
        PRINT   msg_nocard1
        mov     ax, [winseg]
        call    print_hex16
        PRINT   msg_card2
        mov     ax, [port]
        call    print_hex16
        PRINT   msg_nocard2
        mov     al, [id0]
        call    print_hex8
        mov     dl, ' '
        call    print_char
        mov     al, [id0 + 1]
        call    print_hex8
        mov     dx, msg_nocard3
        jmp     die

rom_sig:        db      'ISAFLASH'
msg_card1:      db      'Card: window $'
msg_card2:      db      'h, port $'
msg_card3:      db      'h, $'
msg_card4:      db      ' x 28F008SA ($'
msg_card5:      db      ' KB)', 13, 10, '$'
msg_nocard1:    db      'No 28F008SA at window $'
msg_nocard2:    db      'h (ID $'
msg_nocard3:    db      '). Check SW1/SW2 or use /M:seg /P:port.', 13, 10, '$'
msg_jumper:     db      'VPP is low: fit the WRITE jumper JP1 and run again.', 13, 10, '$'

; ---- variables ----
port            dw      0
winseg          dw      0
bufseg          dw      0
opt_port        dw      0
opt_mem         dw      0
opt_off         dw      0               ; /O: first block (logical block with /D, else 64 KB block)
id0             dw      0
id1             dw      0
opt_flags       db      0
chips           db      0
card_ok         db      0
rom_found       db      0
wb_block        db      0
wb_action       db      0
