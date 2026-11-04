"""全局快捷键（pynput）：按住说话键 + 打字翻译框组合键。

注意：游戏以管理员身份运行时，普通权限的程序收不到按键，需要用管理员身份运行本程序。
"""

from __future__ import annotations

from typing import Callable


def parse_key(name: str):
    from pynput import keyboard

    name = name.strip().lower()
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        raise ValueError(f"无法识别的按键：{name}（可用 f1-f12、caps_lock、alt_r、ctrl_r、单个字母等）")


class Hotkeys:
    def __init__(
        self,
        ptt_key: str | None,
        on_ptt: Callable[[bool], None],
        combo: str | None,
        on_combo: Callable[[], None],
    ):
        from pynput import keyboard

        self.listeners = []
        if ptt_key:
            target = parse_key(ptt_key)

            def same(k) -> bool:
                if isinstance(target, keyboard.KeyCode) and isinstance(k, keyboard.KeyCode):
                    return (k.char or "").lower() == (target.char or "").lower()
                return k == target

            self.listeners.append(
                keyboard.Listener(
                    on_press=lambda k: on_ptt(True) if same(k) else None,
                    on_release=lambda k: on_ptt(False) if same(k) else None,
                )
            )
        if combo:
            self.listeners.append(keyboard.GlobalHotKeys({combo: on_combo}))

    def start(self) -> None:
        for listener in self.listeners:
            listener.daemon = True
            listener.start()

    def stop(self) -> None:
        for listener in self.listeners:
            try:
                listener.stop()
            except Exception:
                pass
