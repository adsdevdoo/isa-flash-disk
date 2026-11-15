; Boot sector of a data-only FAT12 partition made by tools/mkdisk.py without DOS system files.
; mkdisk.py overwrites bytes 03h..3Dh with the BPB; the code starts at 3Eh, like DOS 4+ boot sectors.

        cpu     8086
        bits    16
        org     7C00h

        jmp     short code
        nop
        times 3Eh - ($ - $$) db 0       ; OEM name + BPB + extended BPB, filled in by mkdisk.py

code:   cli
        xor     ax, ax
        mov     ds, ax
        mov     ss, ax
        mov     sp, 7C00h
        sti
        cld
        mov     si, msg
.put:   lodsb
        or      al, al
        jz      .stop
        mov     ah, 0Eh
        xor     bx, bx
        int     10h
        jmp     .put
.stop:  int     18h
.hang:  hlt
        jmp     .hang

msg:    db      'ISA Flash Disk: no operating system on this disk.', 13, 10
        db      'Make it with tools/mkdisk.py --boot (see docs/programming.md).', 13, 10, 0

        times 510 - ($ - $$) db 0
        dw      0AA55h
