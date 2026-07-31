# Compact queue root fix

The previous hard minimum-height change could not solve the issue because the
top-level window had more vertical minimum-size pressure than the available
1366×768 workspace. Qt therefore compressed the table viewport.

Compact workspace mode now removes duplicate queue summary/footer surfaces,
keeps range and command controls available, and shortens the queue heading.
Other workspace profiles retain the complete Queue Pro layout.
