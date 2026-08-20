<?php
/**
 * Plugin Name: Fake Widget Plugin
 * Description: Тестовый плагин-заглушка для проверки эвристики делегирования scout.
 * Version: 1.0.0
 */

if (!defined('ABSPATH')) {
    exit;
}

define('FAKE_WIDGET_PLUGIN_DIR', plugin_dir_path(__FILE__));
define('FAKE_WIDGET_PLUGIN_URL', plugin_dir_url(__FILE__));

require_once FAKE_WIDGET_PLUGIN_DIR . 'includes/class-loader.php';

function fake_widget_plugin_run() {
    $loader = new Fake_Widget_Loader();
    $loader->init();
}
add_action('plugins_loaded', 'fake_widget_plugin_run');
