; ISA Flash Disk master boot record (written by tools/mkdisk.py; the partition table is filled in there).
; Classic chain loader: relocate to 0:0600, find the active partition, load its first sector to 0:7C00 with
; INT 13h (CHS from the partition entry), check 55AAh and jump to it with DL = boot drive, DS:SI = entry.
; 8086 only. Public domain style original code, no MS-DOS FDISK code is used.

        cpu     8086
        bits    16
        org     0600h

start:  cli
        xor     ax, ax
        mov     ss, ax
        mov     sp, 7C00h
        mov     ds, ax
        mov     es, ax
        sti
        cld
        mov     si, 7C00h
        mov     di, 0600h
        mov     cx, 256
        rep     movsw
        jmp     0:reloc

reloc:  mov     si, ptable
        mov     cx, 4
.find:  cmp     byte [si], 80h
        je      .found
        add     si, 16
        loop    .find
        mov     si, msg_noact
        jmp     fail
.found: mov     bp, si
        mov     di, 5
.read:  mov     ax, 0201h
        mov     bx, 7C00h
        mov     dh, [bp + 1]
        mov     cx, [bp + 2]
        int     13h
        jnc     .loaded
        xor     ax, ax
        int     13h
        dec     di
        jnz     .read
        mov     si, msg_read
        jmp     fail
.loaded:
        cmp     word [7DFEh], 0AA55h
        jne     .nosys
        mov     si, bp
        jmp     0:7C00h
.nosys: mov     si, msg_nosys

fail:   lodsb
        or      al, al
        jz      .stop
        mov     ah, 0Eh
        xor     bx, bx
        int     10h
        jmp     fail
.stop:  int     18h                     ; no bootable partition: back to the BIOS
.hang:  hlt
        jmp     .hang

msg_noact:      db      'ISA Flash Disk: no active partition', 13, 10, 0
msg_read:       db      'ISA Flash Disk: read error', 13, 10, 0
msg_nosys:      db      'ISA Flash Disk: partition not bootable', 13, 10, 0

        times 01BEh - ($ - $$) db 0
ptable: times 64 db 0
        dw      0AA55h
