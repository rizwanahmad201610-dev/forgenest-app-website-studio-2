import tkinter as tk

window = tk.Tk()
window.title('My First App')
window.geometry('430x250')
window.configure(bg='#201c39')
label = tk.Label(window, text='Hello from my Python app!',
                 font=('Segoe UI', 18, 'bold'), fg='white', bg='#201c39')
label.pack(expand=True)
window.mainloop()
