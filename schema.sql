CREATE DATABASE IF NOT EXISTS loandesk CHARACTER SET utf8mb4;
USE loandesk;

CREATE TABLE IF NOT EXISTS applications(
  id VARCHAR(32) PRIMARY KEY,
  name VARCHAR(120), email VARCHAR(160), phone VARCHAR(30), pan VARCHAR(12),
  loan_type VARCHAR(40), amount DOUBLE, tenure INT, income DOUBLE, employment VARCHAR(40),
  email_text TEXT, documents LONGTEXT, status VARCHAR(20), decision LONGTEXT, created_at DOUBLE, email_status VARCHAR(16),
  INDEX idx_pan(pan), INDEX idx_status(status));

CREATE TABLE IF NOT EXISTS steps(
  app_id VARCHAR(32), agent VARCHAR(48), status VARCHAR(16), summary TEXT,
  started DOUBLE, finished DOUBLE,
  PRIMARY KEY(app_id, agent));

CREATE TABLE IF NOT EXISTS logs(
  id BIGINT AUTO_INCREMENT PRIMARY KEY, app_id VARCHAR(32), ts DOUBLE, msg TEXT,
  INDEX idx_log_app(app_id));

CREATE TABLE IF NOT EXISTS outbox(
  id BIGINT AUTO_INCREMENT PRIMARY KEY, app_id VARCHAR(32),
  to_addr VARCHAR(160), subject VARCHAR(255), body TEXT, ts DOUBLE, status VARCHAR(255));