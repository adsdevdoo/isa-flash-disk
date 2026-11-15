; dosmacro.inc - macros and option bits for the ISA Flash Disk .COM utilities (include before code).

%ifndef DOSMACRO_INC
%define DOSMACRO_INC

%macro PRINT 1
        mov     dx, %1
        call    print_dollar
%endmacro

OPT_YES         equ     01h             ; /Y  no confirmation
OPT_DISK        equ     02h             ; /D  disk data area only
OPT_JUMPER      equ     04h             ; /J  test the WRITE jumper (programs FFh, which changes nothing)
OPT_ERASE       equ     08h             ; /E  also erase the whole disk area

%endif
