-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,          -- ID пользователя в Telegram (например, "5976186394")
    name TEXT,                    -- Имя (например, "Денис")
    active_trip_id TEXT,          -- ID текущей активной поездки
    state TEXT DEFAULT 'IDLE',    -- Текущее состояние (что делает бот: ждет ввода суммы, названия и т.д.)
    linked_to TEXT,               -- ID "родителя", если это семейный аккаунт
    menu_msg_id INTEGER,          -- ID сообщения с меню (чтобы обновлять его, а не слать новое)
    temp_data_json TEXT,          -- Временные данные (draft_id, temp_trip_id и т.д.)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица поездок
CREATE TABLE IF NOT EXISTS trips (
    id TEXT PRIMARY KEY,          -- ID поездки (например, "trip_1700000000")
    code TEXT UNIQUE,             -- Код для приглашения (например, "A1B2C3")
    creator_id TEXT,              -- Кто создал
    name TEXT,                    -- Название ("Тай 2026")
    rate REAL DEFAULT 0,          -- Курс валюты к рублю
    currency TEXT DEFAULT 'THB',  -- Валюта поездки
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(creator_id) REFERENCES users(id)
);

-- Таблица связи: Пользователь <-> Поездка
-- (Показывает, кто в каких поездках участвует)
CREATE TABLE IF NOT EXISTS trip_members (
    trip_id TEXT,
    user_id TEXT,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trip_id, user_id),
    FOREIGN KEY(trip_id) REFERENCES trips(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Таблица расходов
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- Уникальный номер траты
    trip_id TEXT,                         -- К какой поездке относится
    payer_id TEXT,                        -- Кто платил (физически)
    amount REAL,                          -- Сумма
    description TEXT,                     -- Описание ("Такси", "Обед")
    category TEXT,                        -- Категория (FOOD, TRANSPORT...)
    created_at INTEGER,                   -- Время создания (timestamp)
    
    -- SPLIT (Разделение):
    -- Раньше это был сложный объект внутри JSON.
    -- В SQL обычно делают отдельную таблицу, но для простоты и совместимости
    -- мы можем хранить JSON-строку здесь, либо (лучше) сделать таблицу expense_splits.
    -- Для начала, чтобы не усложнять миграцию, сохраним split как JSON-текст.
    -- Это компромисс, но рабочий для нашего масштаба.
    split_json TEXT,                      -- Например: '{"5976186394": 500, "12345": 500}'
    
    FOREIGN KEY(trip_id) REFERENCES trips(id),
    FOREIGN KEY(payer_id) REFERENCES users(id)
);

-- Таблица заметок
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id TEXT,
    author_name TEXT,
    text TEXT,
    created_at INTEGER,
    FOREIGN KEY(trip_id) REFERENCES trips(id)
);

-- Таблица черновиков (временные данные при создании траты)
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    trip_id TEXT,
    amount REAL,
    description TEXT,
    category TEXT,
    selected_users_json TEXT, -- JSON со списком выбранных участников
    created_at INTEGER
);
