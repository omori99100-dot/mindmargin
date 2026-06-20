@echo off
setlocal
set PYTHON=C:\Users\A Center\AppData\Local\Programs\Python\Python314\python.exe
set ROOT=C:\Users\A Center\OneDrive\المستندات\mindmargin
cd /d "%ROOT%"
"%PYTHON%" -c "import sys; sys.path.insert(0, r'%ROOT%'); import mindmargin.main; mindmargin.main.main()" %*
