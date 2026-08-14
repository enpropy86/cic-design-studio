import sys
import ctypes
import traceback

def main():
    try:
        from PyQt6.QtWidgets import QApplication
        from ui import ModernApp

        app = QApplication(sys.argv)
        window = ModernApp()
        window.show()
        print("Application started...")
        sys.exit(app.exec())
    except BaseException as e:
        with open("crash.log", "w", encoding='utf-8') as f:
            traceback.print_exc(file=f)
        print("Crash logged to crash.log")

if __name__ == "__main__":
    main()