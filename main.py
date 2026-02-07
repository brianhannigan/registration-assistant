import sys
from PySide6.QtWidgets import QApplication
from app.ui_main import MainWindowUI

def main():
    app = QApplication(sys.argv)
    w = MainWindowUI()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
