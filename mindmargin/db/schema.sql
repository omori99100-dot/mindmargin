-- MindMargin PostgreSQL Schema

CREATE TABLE IF NOT EXISTS videos (
    id SERIAL PRIMARY KEY,
    pipeline_id VARCHAR(64) UNIQUE NOT NULL,
    topic VARCHAR(255) NOT NULL,
    title VARCHAR(500),
    video_id VARCHAR(64),
    status VARCHAR(32) DEFAULT 'created',
    file_path TEXT,
    thumbnail_path TEXT,
    duration_s INTEGER,
    resolution VARCHAR(16) DEFAULT '1920x1080',
    publish_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scripts (
    id SERIAL PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id),
    topic VARCHAR(255),
    sections JSONB,
    full_script TEXT,
    word_count INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analytics (
    id SERIAL PRIMARY KEY,
    video_id VARCHAR(64) NOT NULL,
    views INTEGER DEFAULT 0,
    estimated_ctr REAL DEFAULT 0.0,
    average_view_duration_pct REAL DEFAULT 0.0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    checked_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipeline_logs (
    id SERIAL PRIMARY KEY,
    pipeline_id VARCHAR(64) NOT NULL,
    agent VARCHAR(64),
    status VARCHAR(32),
    error TEXT,
    duration_s REAL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS learnings (
    id SERIAL PRIMARY KEY,
    pipeline_id VARCHAR(64),
    recommendations JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS channels (
    id SERIAL PRIMARY KEY,
    channel_id VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(255),
    description TEXT,
    niche VARCHAR(128),
    language VARCHAR(8) DEFAULT 'en',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_configs (
    id SERIAL PRIMARY KEY,
    channel_id INTEGER REFERENCES channels(id),
    agent_name VARCHAR(64) NOT NULL,
    config JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_videos_pipeline_id ON videos(pipeline_id);
CREATE INDEX idx_videos_status ON videos(status);
CREATE INDEX idx_analytics_video_id ON analytics(video_id);
CREATE INDEX idx_pipeline_logs_pipeline_id ON pipeline_logs(pipeline_id);
