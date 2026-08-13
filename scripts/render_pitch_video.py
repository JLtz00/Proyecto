from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg


WIDTH, HEIGHT, FPS = 1280, 720, 24
SLIDES = [
    (10, "La oferta correcta cambia con cada interacción", "Una campaña estática ignora el estado y el resultado de la conversación."),
    (12, "Closed-Loop Next Best Offer", "Reconstruye estado, prioriza Movistar Total y explica la siguiente acción."),
    (13, "CLI000001 · falta internet hogar", "OF005 completa el siguiente paso hacia Movistar Total."),
    (12, "Aceptar no es activar", "La aceptación registra intención. Solo una activación con evidencia cambia productos."),
    (12, "Nuevo estado · elegible MT · OF022", "Un rechazo por precio activa cooldown y evita repetir la misma oferta."),
    (10, "Recuperación sin romper la estrategia", "Movistar Total Básico y una fecha explícita de recontacto."),
    (6, "+7.24% NDCG@3 frente al baseline v2", "Trazable, reproducible y listo para un piloto A/B; sin afirmar causalidad."),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = [
        Path("C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    selected = next((path for path in names if path.exists()), None)
    return ImageFont.truetype(str(selected), size) if selected else ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, selected_font: ImageFont.ImageFont, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=selected_font)[2] <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def frame(title: str, caption: str, index: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#0b1015")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 64, 1210, 570), radius=20, fill="#111820", outline="#33423f", width=2)
    draw.rectangle((70, 64, 78, 570), fill="#79a99d")
    draw.text((110, 105), f"CLOSED-LOOP NBO  ·  {index + 1}/7", font=font(23, True), fill="#79a99d")
    y = 205
    for line in wrap(draw, title, font(48, True), 980):
        draw.text((110, y), line, font=font(48, True), fill="#edf1f4")
        y += 62
    draw.rounded_rectangle((70, 610, 1210, 690), radius=10, fill="#172824")
    lines = wrap(draw, caption, font(25), 1040)
    y = 625 if len(lines) > 1 else 635
    for line in lines:
        draw.text((110, y), line, font=font(25), fill="#dbe6e2")
        y += 31
    return image


def main() -> None:
    output = Path("assets/demo_jury.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)
    executable = imageio_ffmpeg.get_ffmpeg_exe()
    process = imageio_ffmpeg.write_frames(
        str(output), (WIDTH, HEIGHT), fps=FPS, codec="libx264", quality=7,
        output_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    )
    process.send(None)
    for index, (seconds, title, caption) in enumerate(SLIDES):
        pixels = frame(title, caption, index).tobytes()
        for _ in range(seconds * FPS):
            process.send(pixels)
    process.close()
    print(output.resolve())


if __name__ == "__main__":
    main()
