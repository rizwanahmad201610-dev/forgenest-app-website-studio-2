OPEN THIS FIRST
===============
- index.html is in this SAME folder. Double-click it to preview the website instantly.
- To activate actual app/installer building, double-click Start_Website.vbs on Windows.
  It starts the local server and opens the working website in your browser.
- Actual website source: site/index.html, site/styles.css, site/app.js.

FORGENEST · PYTHON + JAVA INSTALLER & WEBSITE STUDIO
==================================================

EASIEST WAY ON WINDOWS (no commands to type)
1. Unzip this entire folder.
2. Double-click Start_Website.vbs.
3. Your web browser opens http://127.0.0.1:8765/ automatically.
4. Select Python or Java, upload your project and image, choose a name, click Build.
5. Click My Projects to download the SINGLE .exe installer.

WHAT IS REQUIRED?
- Windows 10 or 11 and Python 3.9+ already installed (to run this local website).
- Inno Setup 6 or 7 installed (free for noncommercial personal use; check license):
  https://jrsoftware.org/isdl.php
- For PYTHON app builds: installed Python interpreter; PyInstaller.
  The website can install PyInstaller automatically if you tick the option.
- For JAVA app builds: installed JDK 17+ that includes jpackage, with an executable JAR.
  If your JAR lacks a Main-Class manifest, enter the main class when uploading.
- You must build Windows EXE files on a Windows computer. You cannot generate a genuine Windows
  executable just by changing a filename extension on another operating system.

If Start_Website.vbs does not open the website, double-click Start_Website.bat.
This alternative shows a log window with errors. You still do not need to type commands.

WHAT IS INCLUDED?
- Select locally installed versions of Python or Java; version chips show other versions.
- Upload many program files OR an entire folder, choose the app's main .py or .jar file.
- Upload a PNG/JPG/ICO logo. It will become the .exe launcher icon and installer icon.
- Python: PyInstaller produces a single program executable, then Inno Setup produces
  ONE downloadable installer, named YourName_Setup.exe.
- Java: jpackage creates a runtime-inclusive app image, then Inno Setup produces ONE
  downloadable installer containing the Java launcher and necessary files.
- Projects tab stores results on this computer and lets you download the same installer again.
- Project ZIP exports the original source and result for manual transfer to another PC.
- Website builder: free starter template, optional AI site via personal API key,
  or upload existing HTML/CSS/JS site. Download static website as ZIP.
- A free hosting service can give you a subdomain (for example, netlify.app), if its
  name is available. Click New name idea for additional unverified suggestions. The tool does NOT buy or reserve any domain automatically.

IMPORTANT LIMITATIONS
- This is a functional LOCAL website, NOT a hosted public service.
  Opening it from another computer does not automatically sync data. Use project ZIP exports,
  or deploy a shared authenticated server with Windows build workers and persistent storage.
- Installed versions, build tools and app dependencies are prerequisites; the site shows
  clear error messages when something is missing. Java JAR must be executable.
- AI generation sends your prompt to OpenAI only when you choose AI and provide an API key.
  API usage can cost money. The API key is not stored by ForgeNest.
- Building programs can execute code through packaging hooks. Upload ONLY projects you trust.
- The generated EXE may trigger Windows SmartScreen until signed by a trusted publisher.
- Some programs need code changes to locate bundled data using __file__ or sys._MEIPASS.
- A generated installer is one download, but installation naturally creates app files.
- Do not expose this localhost application publicly without authentication and hardening.

LICENSE: Code in this example project may be used and modified for personal projects.

EXAMPLES
- examples/ExamplePython/hello_window.py — try the Python builder.
- examples/ExampleJava/HelloWindow.jar — try the Java builder (JDK 17+).
- examples/ExampleWebsite/index.html — try the Website Builder upload.
