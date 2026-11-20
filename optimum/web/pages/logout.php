<?php
declare(strict_types=1);

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    verify_csrf();
    Auth::logout();
    flash('success', 'Sesión cerrada.');
}
redirect(app_url('login'));
