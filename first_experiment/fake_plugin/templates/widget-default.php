<?php
if (!defined('ABSPATH')) exit;
?>
<div class="fake-widget fake-widget--default">
    <ul>
        <?php for ($i = 1; $i <= $limit; $i++): ?>
            <li>Item <?php echo (int) $i; ?></li>
        <?php endfor; ?>
    </ul>
</div>
