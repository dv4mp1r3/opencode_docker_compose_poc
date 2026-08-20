<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Logger {
    public static function log($message, $level = 'info') {
        if (defined('WP_DEBUG') && WP_DEBUG) {
            error_log("[fake-widget][{$level}] {$message}");
        }
    }
}
