-- Migration: Add release_label to stories table
ALTER TABLE stories ADD COLUMN release_label VARCHAR(64) DEFAULT NULL AFTER priority;
