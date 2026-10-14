"""Тексты бота (RU / EN). Подстановки экранируются вызывающим кодом (HTML)."""
from __future__ import annotations

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "choose_lang": "🌐 Выберите язык интерфейса\nChoose your language",
        "welcome": (
            "Привет, <b>{name}</b>! 👋\n\n"
            "Здесь вся музыка из канала <b>{channel}</b> — новинки, популярное, альбомы и плеер "
            "прямо внутри Telegram.\n\nНажми кнопку ниже, чтобы начать слушать."
        ),
        "lang_set": "✅ Язык интерфейса: русский",
        "open": "🎧 Открыть плеер",
        "admin_panel": "⚙️ Панель управления",
        "shared_track": "🎵 С вами поделились треком:\n<b>{title}</b>",
        "shared_album": "💿 С вами поделились альбомом <b>{title}</b>",
        "listen": "▶️ Слушать",
        "open_album": "💿 Открыть альбом",
        "not_found": "Похоже, этот трек или альбом больше недоступен.",
        "stats": (
            "📊 <b>Статистика</b>\n\n"
            "👥 Пользователи: {users_total} (+{users_today} сегодня)\n"
            "🔥 Активны за сутки: {dau}\n"
            "🎵 Треков: {tracks_total}\n"
            "▶️ Прослушиваний: {plays_total} ({plays_today} сегодня)\n"
            "❤️ В избранном: {favorites_total}"
        ),
        "sync_running": "Синхронизация уже идёт…",
        "sync_start": "🔄 Запускаю полную синхронизацию канала…",
        "sync_done": "✅ Готово: просмотрено {scanned} сообщений, треков {found}, удалено {deleted}.",
        "sync_error": "⚠️ Ошибка синхронизации: {error}",
        "menu": "Музыка",
        "cmd_start": "Открыть музыкальное приложение",
        "cmd_language": "Сменить язык",
        "cmd_upload": "Предложить свои треки",
        "upload_button": "➕ Предложить свои треки",
        "upload_intro": (
            "🎵 <b>Предложите свои треки</b>\n\n"
            "Отправьте сюда mp3-файлы — можно сразу несколько.\n"
            "• до <b>{batch}</b> треков в одной заявке\n"
            "• не больше <b>{day}</b> треков в сутки\n"
            "• только <b>mp3</b>, до {size} МБ, до {minutes} минут\n"
            "• жанр или тег — по желанию: напишите отдельным сообщением или в подписи к файлу (например <code>#rock</code>)\n\n"
            "После проверки администратором треки появятся в канале и в приложении."
        ),
        "upload_summary": "📥 <b>Ваша заявка</b> — треков: {n} из {batch}\n\n{files}\n\n🏷 Жанр/тег: {tags}",
        "upload_no_tags": "не указан",
        "upload_hint": "Чтобы указать жанр или тег, отправьте его сообщением. Затем нажмите «Отправить на проверку».",
        "upload_send": "📨 Отправить на проверку",
        "upload_cancel": "🗑 Отменить",
        "upload_sent": "✅ Треки отправлены на проверку. Мы пришлём уведомление о решении.",
        "upload_cancelled": "Заявка отменена.",
        "upload_empty": "В заявке пока нет треков — отправьте mp3-файлы.",
        "upload_warn_format": "⚠️ Принимаются только mp3-файлы — {n} файл(ов) пропущено.",
        "upload_warn_size": "⚠️ Файл слишком большой или длинный (лимит {size} МБ / {minutes} мин) — пропущено: {n}.",
        "upload_warn_batch": "⚠️ В одной заявке не больше {batch} треков — лишние ({n}) не добавлены. Отправьте эту заявку и пришлите остальные.",
        "upload_warn_day": "⚠️ Дневной лимит — {day} треков в сутки. Попробуйте завтра (не добавлено: {n}).",
        "upload_warn_pending": "⚠️ У вас уже есть заявки на проверке ({n}). Дождитесь решения, прежде чем отправлять новые.",
        "upload_tags_set": "🏷 Жанр/тег сохранён: {tags}",
        "upload_tags_bad": "Не удалось распознать тег. Используйте буквы и цифры, например: rock, хип_хоп.",
        "upload_approved": "🎉 Ваша заявка одобрена! Опубликовано треков: <b>{n}</b>. Они уже в канале и в приложении.",
        "upload_rejected": "😔 Ваше предложение отклонено.",
        "upload_reason": "Причина: {reason}",
        "flags_reason": "Комментарий администратора: {reason}",
        "admin_new_submission": "📥 <b>Новая заявка #{id}</b>\nОт: {name}\nТреков: {n}\nТеги: {tags}",
        "banned": "⛔ Доступ к приложению ограничен администратором.",
        "upload_restricted": "🚫 Возможность предлагать треки для вас ограничена администратором.",
        "flags_title": "🔔 <b>Изменения в вашем аккаунте</b>",
        "flag_vip_on": "⭐ Вам выдан <b>Premium</b>! Теперь доступно: до {batch} треков в заявке и {day} в сутки, до {albums} альбомов и особое оформление профиля.",
        "flag_vip_off": "Статус Premium снят.",
        "flag_banned_on": "⛔ Доступ к приложению и боту заблокирован.",
        "flag_banned_off": "✅ Доступ к приложению восстановлен.",
        "flag_no_albums_on": "🚫 Создание и изменение альбомов ограничено.",
        "flag_no_albums_off": "✅ Вы снова можете создавать и изменять альбомы.",
        "flag_no_uploads_on": "🚫 Возможность предлагать треки ограничена.",
        "flag_no_uploads_off": "✅ Вы снова можете предлагать свои треки.",
        "flag_name": "✏️ Ваше имя в приложении: <b>{name}</b>",
        "flag_name_reset": "✏️ Имя в приложении снова берётся из Telegram.",
    },
    "en": {
        "choose_lang": "🌐 Choose your language\nВыберите язык интерфейса",
        "welcome": (
            "Hi, <b>{name}</b>! 👋\n\n"
            "All the music from <b>{channel}</b> is here — new releases, popular tracks, albums "
            "and a player right inside Telegram.\n\nTap the button below to start listening."
        ),
        "lang_set": "✅ Interface language: English",
        "open": "🎧 Open player",
        "admin_panel": "⚙️ Admin panel",
        "shared_track": "🎵 A track was shared with you:\n<b>{title}</b>",
        "shared_album": "💿 An album was shared with you: <b>{title}</b>",
        "listen": "▶️ Listen",
        "open_album": "💿 Open album",
        "not_found": "Looks like this track or album is no longer available.",
        "stats": (
            "📊 <b>Statistics</b>\n\n"
            "👥 Users: {users_total} (+{users_today} today)\n"
            "🔥 Active today: {dau}\n"
            "🎵 Tracks: {tracks_total}\n"
            "▶️ Plays: {plays_total} ({plays_today} today)\n"
            "❤️ Favorites: {favorites_total}"
        ),
        "sync_running": "Sync is already running…",
        "sync_start": "🔄 Starting full channel sync…",
        "sync_done": "✅ Done: scanned {scanned} messages, tracks {found}, removed {deleted}.",
        "sync_error": "⚠️ Sync error: {error}",
        "menu": "Music",
        "cmd_start": "Open the music app",
        "cmd_language": "Change language",
        "cmd_upload": "Submit your tracks",
        "upload_button": "➕ Submit your tracks",
        "upload_intro": (
            "🎵 <b>Submit your tracks</b>\n\n"
            "Send mp3 files here — several at once is fine.\n"
            "• up to <b>{batch}</b> tracks per submission\n"
            "• no more than <b>{day}</b> tracks per day\n"
            "• <b>mp3</b> only, up to {size} MB and {minutes} minutes\n"
            "• genre or tag is optional: send it as a separate message or in the file caption (e.g. <code>#rock</code>)\n\n"
            "After moderation the tracks will appear in the channel and in the app."
        ),
        "upload_summary": "📥 <b>Your submission</b> — tracks: {n} of {batch}\n\n{files}\n\n🏷 Genre/tag: {tags}",
        "upload_no_tags": "not set",
        "upload_hint": "To set a genre or tag, send it as a message. Then tap “Send for review”.",
        "upload_send": "📨 Send for review",
        "upload_cancel": "🗑 Cancel",
        "upload_sent": "✅ Tracks sent for review. We will notify you about the decision.",
        "upload_cancelled": "Submission cancelled.",
        "upload_empty": "No tracks yet — send mp3 files.",
        "upload_warn_format": "⚠️ Only mp3 files are accepted — {n} file(s) skipped.",
        "upload_warn_size": "⚠️ File is too large or too long (limit {size} MB / {minutes} min) — skipped: {n}.",
        "upload_warn_batch": "⚠️ Up to {batch} tracks per submission — extra files ({n}) were not added. Send this one and then the rest.",
        "upload_warn_day": "⚠️ Daily limit is {day} tracks. Try again tomorrow (not added: {n}).",
        "upload_warn_pending": "⚠️ You already have submissions under review ({n}). Please wait for the decision first.",
        "upload_tags_set": "🏷 Genre/tag saved: {tags}",
        "upload_tags_bad": "Could not recognise the tag. Use letters and digits, e.g. rock, hip_hop.",
        "upload_approved": "🎉 Your submission was approved! Tracks published: <b>{n}</b>. They are already in the channel and the app.",
        "upload_rejected": "😔 Your submission was declined.",
        "upload_reason": "Reason: {reason}",
        "flags_reason": "Administrator's comment: {reason}",
        "admin_new_submission": "📥 <b>New submission #{id}</b>\nFrom: {name}\nTracks: {n}\nTags: {tags}",
        "banned": "⛔ Your access to the app has been restricted by an administrator.",
        "upload_restricted": "🚫 Submitting tracks has been restricted for you by an administrator.",
        "flags_title": "🔔 <b>Changes to your account</b>",
        "flag_vip_on": "⭐ You've got <b>Premium</b>! Now available: up to {batch} tracks per submission and {day} per day, up to {albums} albums and a special profile look.",
        "flag_vip_off": "Your Premium status has been removed.",
        "flag_banned_on": "⛔ Access to the app and the bot has been blocked.",
        "flag_banned_off": "✅ Access to the app has been restored.",
        "flag_no_albums_on": "🚫 Creating and editing albums has been restricted.",
        "flag_no_albums_off": "✅ You can create and edit albums again.",
        "flag_no_uploads_on": "🚫 Submitting tracks has been restricted.",
        "flag_no_uploads_off": "✅ You can submit your tracks again.",
        "flag_name": "✏️ Your name in the app: <b>{name}</b>",
        "flag_name_reset": "✏️ Your name in the app is taken from Telegram again.",
    },
}


def t(lang: str | None, key: str, **kwargs: object) -> str:
    table = TEXTS.get(lang or "", TEXTS["en"])
    text = table.get(key) or TEXTS["en"][key]
    return text.format(**kwargs) if kwargs else text


def guess_lang(language_code: str | None) -> str:
    return "ru" if (language_code or "").split("-")[0] in ("ru", "uk", "be", "kk") else "en"
