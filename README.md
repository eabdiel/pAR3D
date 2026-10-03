# pAR3D by ProgreTech

Windows desktop and camera to side-by-side 3D for AR glasses, using AI depth estimation with optional GPU acceleration.

A project of **[ProgreTech LLC](https://progretech.com)**, owned and maintained by **Ed Rodriguez**. Third-party components and contributions retain their respective ownership and notices.

[Project website](https://progretech.com) · [Report an issue](https://github.com/eabdiel/pAR3D/issues) · [Contribute](CONTRIBUTING.md)

**pAR3D** is a real-time side-by-side (SBS) 3D visualization tool that transforms your desktop or camera feed into a stereoscopic depth experience using modern AI depth estimation.

It is designed for experimentation, visualization, and creative exploration of real-time depth-based rendering on standard consumer hardware (like xReal, Viture and Rokid AR Glasses).

---

## ✨ Features

- Real-time SBS (Side-By-Side) 3D rendering  
- Desktop capture or camera feed input  
- AI-powered depth estimation using **Depth Anything v2**  
- Adjustable depth strength, scale, and FPS  
- Performance modes (High / Balanced / Eco)  
- Tray icon with quick controls  
- Fullscreen and windowed modes  
  - Double-click to exit fullscreen  
- Persistent user settings (saved automatically)  
- Optional GPU acceleration (CUDA) when available  
- Clean shutdown and low system impact when idle  

---

## 🖥️ System Requirements

- Python 3.9+
- Windows 10 / 11
- CPU-only or APU-only systems are supported
- NVIDIA GPU (optional, for acceleration)

---

## 📦 Installation

Clone the repository:

```bash
git clone https://github.com/eabdiel/pAR3D.git
cd pAR3D
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## ▶️ Running the App

```bash
python pAR3D.py
```

### Recommended CPU settings

```bash
python pAR3D.py --scale 0.5 --depth-every 3 --target-fps 15
```

If CUDA is available, the app will automatically use it.

---

## ⚙️ Controls & Behavior

### Tray Menu

- Start / Stop processing  
- Switch input source (Desktop / Camera)  
- Performance Mode:
  - High (default)
  - Balanced
  - Eco
- Fullscreen toggle  
- About / Exit  

### Window Controls

- Double-click the window to exit fullscreen  
- Settings persist automatically between runs  

---

## 🎨 Assets & Icons

Icons are stored in the `assets/` folder:

```
assets/
 ├─ pAR3D_icon.png
 └─ pAR3D.ico
```

These are used for:
- Tray icon
- Taskbar icon
- Executable packaging

---

## 📦 Building an Executable (Optional)

Using PyInstaller:

```bash
pyinstaller --onefile --windowed --icon assets/pAR3D.ico pAR3D.py
```

---

## 🔧 Configuration

User preferences are stored automatically in a small JSON file in your home directory.  
No manual editing required.

---

## 📜 License & Attribution

**pAR3D**  
Developed by **Edwin Rodriguez**  
Project: **ProgreTech**

GitHub: https://github.com/eabdiel  
Repository: **pAR3D**

This project is provided for educational and experimental use.  
No warranties are provided.

---

## 🚧 Roadmap (Ideas)

- Animated tray icon (depth pulse)
- Per-monitor profiles
- VR headset SBS output mode
- Optional depth smoothing filters
- Plugin-based render effects

## Collaboration

Reproducible bug reports, platform compatibility, installation documentation, and small regression fixes are useful ways to help. Read [CONTRIBUTING.md](CONTRIBUTING.md) for issue reports, proposed changes, and attribution requirements.

## License and reuse

The repository includes GPL-3.0 terms in [LICENSE](LICENSE). Preserve applicable copyright and license notices. Consult the full license for modification, distribution, and any source-provision requirements.

Depth Anything V2 model checkpoints have separate upstream terms. Confirm the exact checkpoint before redistribution or commercial use: [upstream licensing](https://github.com/DepthAnything/Depth-Anything-V2#license). The application’s GPL license does not relicense model weights.

## More from ProgreTech

Explore [CodeSeal](https://codeseal.progretech.com) for signed software provenance and project history.

Discover the wider portfolio at [progretech.com](https://progretech.com). These links identify related products; they do not imply a bundled integration or shared license.
