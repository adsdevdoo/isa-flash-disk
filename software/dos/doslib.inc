; doslib.inc - console output, numbers and command-line parsing for the ISA Flash Disk .COM utilities.
; 8086 only. DS = CS (tiny model).

print_dollar:
        push    ax
        mov     ah, 09h
        int     21h
        pop     ax
        ret

print_char:                             ; DL
        push    ax
        mov     ah, 02h
        int     21h
        pop     ax
        ret

print_crlf:
        push    dx
        mov     dl, 13
        call    print_char
        mov     dl, 10
        call    print_char
        pop     dx
        ret

print_hex16:                            ; AX
        push    ax
        mov     al, ah
        call    print_hex8
        pop     ax
print_hex8:                             ; AL
        push    ax
        push    cx
        push    dx
        mov     ah, al
        mov     cl, 4
        shr     al, cl
        call    .nib
        mov     al, ah
        and     al, 0Fh
        call    .nib
        pop     dx
        pop     cx
        pop     ax
        ret
.nib:   add     al, '0'
        cmp     al, '9'
        jbe     .out
        add     al, 'A' - '9' - 1
.out:   mov     dl, al
        jmp     print_char

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
.put:   pop     dx
        add     dl, '0'
        call    print_char
        loop    .put
        pop     dx
        pop     cx
        pop     bx
        pop     ax
        ret

; parse_hex: DS:SI -> AX, SI past the digits. CF = no digits.
parse_hex:
        xor     ax, ax
        xor     cx, cx                  ; digit count
.next:  mov     bl, [si]
        cmp     bl, 'a'
        jb      .up
        cmp     bl, 'z'
        ja      .up
        sub     bl, 20h
.up:    sub     bl, '0'
        jb      .end
        cmp     bl, 9
        jbe     .dig
        sub     bl, 'A' - '0' - 10
        cmp     bl, 10
        jb      .end
        cmp     bl, 15
        ja      .end
.dig:   push    cx
        mov     cl, 4
        shl     ax, cl
        pop     cx
        or      al, bl
        inc     si
        inc     cx
        jmp     .next
.end:   or      cx, cx
        jnz     .ok
        stc
        ret
.ok:    clc
        ret

; parse_args: PSP command tail -> opt_flags, opt_port, opt_mem, fname (ASCIIZ, empty if none).
parse_args:
        mov     si, 81h
        mov     cl, [80h]
        xor     ch, ch
        mov     bx, si
        add     bx, cx
        mov     byte [bx], 0            ; terminate the tail
        mov     di, fname
.skip:  lodsb
        or      al, al
        jz      .done
        cmp     al, ' '
        je      .skip
        cmp     al, 9
        je      .skip
        cmp     al, '/'
        je      .opt
        cmp     al, '-'
        je      .opt
        cmp     byte [fname], 0         ; first word = file name
        jne     .bad
.name:  stosb
        lodsb
        or      al, al
        jz      .nameend
        cmp     al, ' '
        je      .nameend
        cmp     al, 9
        jne     .name
.nameend:
        mov     byte [di], 0
        dec     si
        jmp     .skip
.opt:   lodsb
        and     al, 0DFh                ; upper case
        cmp     al, 'Y'
        je      .y
        cmp     al, 'D'
        je      .d
        cmp     al, 'J'
        je      .j
        cmp     al, 'E'
        je      .e
        cmp     al, 'P'
        je      .p
        cmp     al, 'M'
        je      .m
        cmp     al, 'O'
        je      .o
        cmp     al, 'A'
        je      .a
        cmp     al, 'T'
        je      .t
.bad:   PRINT   msg_badarg
        stc
        ret
.y:     or      byte [opt_flags], OPT_YES
        jmp     .skip
.d:     or      byte [opt_flags], OPT_DISK
        jmp     .skip
.j:     or      byte [opt_flags], OPT_JUMPER
        jmp     .skip
.e:     or      byte [opt_flags], OPT_ERASE
        jmp     .skip
.a:     or      byte [opt_flags], OPT_ALL
        jmp     .skip
.t:     or      byte [opt_flags], OPT_TEST
        jmp     .skip
.p:     cmp     byte [si], ':'
        jne     .bad
        inc     si
        call    parse_hex
        jc      .bad
        mov     [opt_port], ax
        jmp     .skip
.m:     cmp     byte [si], ':'
        jne     .bad
        inc     si
        call    parse_hex
        jc      .bad
        mov     [opt_mem], ax
        jmp     .skip
.o:     cmp     byte [si], ':'
        jne     .bad
        inc     si
        call    parse_hex
        jc      .bad
        mov     [opt_off], ax
        jmp     .skip
.done:  clc
        ret

; ask_yes: prints DX, waits for a key; ZF = 1 when the answer is Y.
ask_yes:
        test    byte [opt_flags], OPT_YES
        jnz     .yes
        call    print_dollar
        mov     ah, 01h
        int     21h
        push    ax
        call    print_crlf
        pop     ax
        and     al, 0DFh
        cmp     al, 'Y'
        ret
.yes:   cmp     al, al
        ret

; exit with code AL after putting the card into a safe state
exit_prog:
        push    ax
        call    card_safe
        pop     ax
        mov     ah, 4Ch
        int     21h

; die: print DX, exit with code 1
die:    call    print_dollar
        mov     al, 1
        jmp     exit_prog

msg_badarg:     db      'Bad command line.', 13, 10, '$'
