# Telegram Bot (Raspberry Pi 5)

Проект Telegram-бота на Python с запуском в Docker.

## Что умеет программа
- Отвечает пользователям с учетом системного промпта и контекста диалога.
- Ведет базу пользователей в `users.db` и сохраняет историю сообщений в `user_logs/`.
- Поддерживает сбор контактных данных: телефон и email.
- Экспортирует пользователей в CSV (`/exportusers`).
- Делает массовые рассылки:
  - всем пользователям (`/broadcast`)
  - из файла `message.txt` (`/broadcastfile`)
  - по списку ID (`/broadcastids`)
- Управляет списком ID для рассылок (`/addid`, `/removeid`, `/clearids`, `/broadcastlist`).
- Показывает статистику и сервисную информацию (`/stats`, `/userinfo`, `/getlog`, `/listlogs`, `/synclogs`).
- Использует локальную базу знаний из `knowledge_base.json` и fallback на AI-ответ.

## Требования
- Raspberry Pi 5
- Docker и Docker Compose
- Файл `.env` с переменными окружения

## Структура проекта
- `bot.py` — основной код бота
- `docker-compose.yml` — конфигурация сервиса
- `dockerfile` — сборка образа
- `CHANGELOG.md` — журнал дополнений и изменений
- `users.db` — база пользователей
- `user_logs/` — логи пользователей
- `exports/` — экспортированные данные
- `system_prompt.txt` — системный промпт

## Журнал изменений
- Все изменения и дополнения по коду фиксируются в `CHANGELOG.md`.

## Запуск
```bash
docker compose up -d
```

## Пересборка и перезапуск
```bash
docker compose up -d --build telegram-bot
```

## Остановка
```bash
docker compose stop telegram-bot
```

## Проверка статуса
```bash
docker ps
```

## Логи контейнера
```bash
docker logs -f eltavr-bot
```
