# Баннер Thorny Times для Discord Times

Скрипт `patch_dt.py` добавляет в главное меню «Времён раздора» (Discord Times,
`DiscordTimes.exe`) баннер новой игры **Thorny Times** от тех же разработчиков.

Что делает патч:

- в правом нижнем углу главного меню появляется капсула Thorny Times с подписью
  (по умолчанию: `Новая игра от разработчиков "Времён раздора"`);
- при наведении курсора край капсулы подсвечивается золотом и звучит звук меню;
- щелчок открывает страницу игры в Steam и сворачивает игру.

Проверено на Discord Times 1.8.1 с Community Update 1.2 и на нестабильной сборке
Community Update от 2026-11-12. Другие версии скрипт отклоняет и файл не меняет:
он проверяет байты игры по нужным адресам.

## Как запустить

Нужен Python 3.8 или новее. Внешних библиотек не нужно.

Windows:

    py patch_dt.py "C:\Games\Discord Times\DiscordTimes.exe"

Linux и macOS:

    python3 patch_dt.py "/путь/к/DiscordTimes.exe"

Перед изменением скрипт сохраняет оригинал рядом с игрой как `DiscordTimes.exe.bak`.
Пропатчить уже пропатченный файл нельзя: скрипт попросит сначала вернуть оригинал.

Вернуть оригинал:

    py patch_dt.py "C:\Games\Discord Times\DiscordTimes.exe" --restore

Параметры:

- `--image ФАЙЛ` картинка PNG (8 бит, RGB или RGBA; по умолчанию `capsule.png` рядом со скриптом);
- `--url АДРЕС` ссылка, которая открывается по щелчку (по умолчанию страница Steam);
- `--caption ТЕКСТ` подпись над баннером. Только символы шрифта игры: латиница, кириллица,
  цифры и знаки `\ = - + ? ! , . ' " : ; ( ) < > / % @ _`. Кавычки только прямые (`"`),
  в шрифте игры нет «ёлочек». Не больше 255 байт в кодировке cp1251;
- `--restore` вернуть оригинал из `.bak` и удалить `.bak`.

Игра должна быть закрыта, когда запускаете скрипт.

Файлов игры в репозитории нет. `capsule.png` это капсула Thorny Times для Steam,
сделана Aterdux и используется с разрешения авторов.

---

# Thorny Times banner for Discord Times

`patch_dt.py` adds a Thorny Times banner to the main menu of Discord Times
(`DiscordTimes.exe`): the new game by the same developers. The banner is a Steam
capsule with a caption at the bottom right of the menu. Hovering lights a gold edge
and plays the menu bell; a click opens the Steam page and minimises the game.

Checked on Discord Times 1.8.1 with Community Update 1.2 and on the unstable
Community Update build of 2026-11-12. Other builds are refused and the file is not
changed: the script checks the game's bytes at the addresses it needs.

## Usage

Python 3.8 or newer. No third-party packages.

Windows:

    py patch_dt.py "C:\Games\Discord Times\DiscordTimes.exe"

Linux and macOS:

    python3 patch_dt.py "/path/to/DiscordTimes.exe"

Before patching, the original is saved next to the game as `DiscordTimes.exe.bak`.
A patched file is refused by a second run: restore the original first.

Undo:

    py patch_dt.py "C:\Games\Discord Times\DiscordTimes.exe" --restore

Options:

- `--image FILE` picture, 8-bit PNG (RGB or RGBA; default `capsule.png` next to the script);
- `--url URL` link opened on click (default: the Steam page);
- `--caption TEXT` caption under the banner. Only characters of the game's font: Latin,
  Cyrillic, digits and `\ = - + ? ! , . ' " : ; ( ) < > / % @ _`. Straight double quotes
  only (the font has no « »). At most 255 bytes in cp1251;
- `--restore` put the original back from `.bak` and delete `.bak`.

Close the game before running the script.

No game files are in this repository. `capsule.png` is the Thorny Times Steam capsule,
by Aterdux, used with their permission.

## How it works

- A new PE section `.banner` is appended to the file. It holds the code, the caption,
  the link, the open verb and two 231x87 pictures (normal and lit). The existing sections
  are not changed. Data after the last section (the checked builds have some) stays where
  it is, and the new section is placed after it.
- Two hooks:
  - `0x4d2a27` BuildMainMenu: `call AddChild; ret` (6 bytes) becomes `jmp build_hook; nop`.
    `build_hook` adds a hotspot widget (VMT pointer at `0x473ebc`) to the main menu window
    (`0x6594c8`) over the banner rectangle and sets its enter, leave, press and click callbacks.
  - `0x4c7d24` the menu background draw: `call SurfUnlock` becomes `call draw_hook`.
    `draw_hook` builds both pictures on the first call, draws the picture and the caption,
    and jumps to `SurfUnlock` (`0x476d68`).
- Game functions reused: `AddChild` 0x47f6bc, widget constructor 0x4797f0, `ImgNew` 0x4774a0,
  `RGB` 0x476374, `SurfDraw` 0x476ea8, `TextMeasure` 0x4788ec, `SurfTextDraw` 0x478cac,
  `SurfUnlock` 0x476d68, `Sound_Play` 0x481420. Sounds at `0xae1244` (select) and `0xae125c`
  (press); the caption uses the copyright-line font at `0xae24dc`. `ShellExecuteA` and
  `ShowWindow` are called through the import table (`0xc0b778`, `0xc0b5e0`).
- The machine code is assembled by `tools/build_code.py` from the assembly in that file
  (its docstring lists the addresses). It writes the generated block at the top of
  `patch_dt.py`: the code, the list of 34 absolute and 11 relative addresses that the
  patcher adjusts to the section's address, and the data layout. To regenerate it:
  `pip install keystone-engine`, then `python tools/build_code.py`.
- Tests: `python -m unittest discover -s tests`. With `DT_EXE=/path/to/DiscordTimes.exe` set,
  the end-to-end tests also run on that exe (on a temporary copy).
