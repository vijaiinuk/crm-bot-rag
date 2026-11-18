-- Runs once, when the data volume is first created.
-- A separate database for DB tests, so they never touch dev data.
CREATE DATABASE chatbot_test OWNER chatbot;
