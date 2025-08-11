import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Scheme = "light" | "dark";

interface TelegramUser {
  id: number;
  is_bot?: boolean;
  first_name: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  photo_url?: string;
  is_premium?: boolean;
  added_to_attachment_menu?: boolean;
  allows_write_to_pm?: boolean;
}

interface ThemeParams {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
}

interface MainButton {
  setText: (text: string) => void;
  onClick: (handler: () => void) => void;
  offClick: (handler: () => void) => void;
  show: () => void;
  hide: () => void;
}

interface BackButton {
  onClick: (handler: () => void) => void;
  offClick: (handler: () => void) => void;
  show: () => void;
  hide: () => void;
}

interface TelegramWebApp {
  expand?: () => void;
  ready?: () => void;
  colorScheme?: Scheme;
  themeParams?: ThemeParams;
  user?: TelegramUser;
  setBackgroundColor?: (color: string) => void;
  setHeaderColor?: (color: string) => void;
  onEvent?: (eventType: string, handler: () => void) => void;
  offEvent?: (eventType: string, handler: () => void) => void;
  MainButton?: MainButton;
  BackButton?: BackButton;
  sendData?: (data: string) => void;
}

interface TelegramWindow extends Window {
  Telegram?: { WebApp?: TelegramWebApp };
}

export const useTelegram = (
  forceLight: boolean = import.meta.env.VITE_FORCE_LIGHT === "true",
) => {
  const tg = useMemo<TelegramWebApp | null>(
    () => (window as TelegramWindow)?.Telegram?.WebApp ?? null,
    [],
  );
  const [isReady, setReady] = useState<boolean>(false);
  const [user, setUser] = useState<TelegramUser | null>(null);
  const [colorScheme, setScheme] = useState<Scheme>("light");
  const mainClickRef = useRef<(() => void) | null>(null);
  const backClickRef = useRef<(() => void) | null>(null);

  const applyTheme = useCallback(
    (src: TelegramWebApp | null, ignoreScheme = false) => {
      const root = document.documentElement;
      const p = src?.themeParams ?? {};
      const map: Record<string, string | undefined> = {
        "--tg-theme-bg-color": p.bg_color,
        "--tg-theme-text-color": p.text_color,
        "--tg-theme-hint-color": p.hint_color,
        "--tg-theme-link-color": p.link_color,
        "--tg-theme-button-color": p.button_color,
        "--tg-theme-button-text-color": p.button_text_color,
        "--tg-theme-secondary-bg-color": p.secondary_bg_color,
      };
      if (ignoreScheme) {
        // Remove Telegram theme overrides to fall back to default light colors
        Object.keys(map).forEach((k) => root.style.removeProperty(k));
        root.classList.remove("dark");
        root.style.colorScheme = "light";
        setScheme("light");
        src?.setBackgroundColor?.("#ffffff");
        src?.setHeaderColor?.("#ffffff");
      } else {
        Object.entries(map).forEach(([k, v]) => v && root.style.setProperty(k, v));
        root.style.colorScheme = "";
        root.classList.toggle("dark", src?.colorScheme === "dark");
        setScheme(src?.colorScheme ?? "light");
      }
    },
    [],
  );

  useEffect(() => {
    if (!tg) {
      console.warn("[TG] not in Telegram, enabling dev fallback");
      applyTheme(null, forceLight);
      setReady(true);
      return;
    }
    try {
      tg.expand?.();
      tg.ready?.();
      applyTheme(tg, forceLight);
      setUser(tg.user ?? null);
      setReady(true);
      const onTheme = () => applyTheme(tg, forceLight);
      tg.onEvent?.("themeChanged", onTheme);
      return () => {
        tg.offEvent?.("themeChanged", onTheme);
        if (mainClickRef.current) tg.MainButton?.offClick?.(mainClickRef.current);
        if (backClickRef.current) tg.BackButton?.offClick?.(backClickRef.current);
      };
    } catch (e) {
      console.error("[TG] init error:", e);
      setReady(true);
    }
  }, [tg, applyTheme, forceLight]);

  const sendData = (data: unknown) => tg?.sendData?.(JSON.stringify(data));

  const showMainButton = (text: string, onClick: () => void) => {
    if (!tg?.MainButton) return;
    if (mainClickRef.current) tg.MainButton.offClick?.(mainClickRef.current);
    mainClickRef.current = onClick;
    tg.MainButton.setText(text);
    tg.MainButton.onClick(onClick);
    tg.MainButton.show();
  };
  const hideMainButton = () => tg?.MainButton?.hide?.();

  const showBackButton = (onClick: () => void) => {
    if (!tg?.BackButton) return;
    if (backClickRef.current) tg.BackButton.offClick?.(backClickRef.current);
    backClickRef.current = onClick;
    tg.BackButton.onClick(onClick);
    tg.BackButton.show();
  };
  const hideBackButton = () => tg?.BackButton?.hide?.();

  return { tg, isReady, user, colorScheme, sendData, showMainButton, hideMainButton, showBackButton, hideBackButton };
};
