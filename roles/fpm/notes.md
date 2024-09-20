
destination:     /etc/php/8.2/mods-available/opcache.ini
debian link to : /etc/php/8.2/fpm/conf.d/10-opcache.ini


# before

## run 1

Donnerstag 05 Januar 2023  08:13:57 +0100 (0:00:01.274)       0:01:43.936 *****
===============================================================================
ansible-php : ensure PHP packages are installed. ----------------------- 23.30s
ansible-php : configure modules ----------------------------------------- 9.27s
ansible-php : disable modules ------------------------------------------- 6.63s
ansible-php : enable modules -------------------------------------------- 6.56s
ansible-php : create php.ini configuration files ------------------------ 6.35s
ansible-php : install dependencies -------------------------------------- 5.00s
ansible-php : update package -------------------------------------------- 4.81s
ansible-php : ensure configuration directories exist -------------------- 4.33s
ansible-php : create php-fpm.conf --------------------------------------- 3.11s
ansible-php : create sury-php source list ------------------------------- 2.90s
ansible-php : update package cache -------------------------------------- 2.68s
ansible-php : detect available php version ------------------------------ 2.58s
ansible-php : add apt signing key (debian) ------------------------------ 2.56s
ansible-php : create pool configuration --------------------------------- 2.56s
ansible-php : create local facts ---------------------------------------- 2.50s
Gathering Facts --------------------------------------------------------- 2.04s
ansible-php : do facts module to get latest information ----------------- 1.48s
ansible-php : ensure php-fpm is started and enabled at boot ------------- 1.47s
ansible-php : make sure python3-apt is installed (only debian based) ---- 1.30s
ansible-php : restart php-fpm ------------------------------------------- 1.27s

## run 2

Donnerstag 05 Januar 2023  08:16:29 +0100 (0:00:01.615)       0:01:06.631 *****
===============================================================================
ansible-php : enable modules -------------------------------------------- 6.63s
ansible-php : disable modules ------------------------------------------- 6.55s
ansible-php : configure modules ----------------------------------------- 5.21s
ansible-php : ensure configuration directories exist -------------------- 4.41s
ansible-php : create php.ini configuration files ------------------------ 3.39s
ansible-php : detect available php version ------------------------------ 2.91s
ansible-php : update package -------------------------------------------- 2.70s
ansible-php : update package cache -------------------------------------- 2.60s
ansible-php : make sure python3-apt is installed (only debian based) ---- 2.28s
ansible-php : install dependencies -------------------------------------- 2.23s
ansible-php : ensure PHP packages are installed. ------------------------ 2.22s
Gathering Facts --------------------------------------------------------- 2.05s
ansible-php : create sury-php source list ------------------------------- 1.91s
ansible-php : create php-fpm.conf --------------------------------------- 1.79s
ansible-php : create pool configuration --------------------------------- 1.74s
ansible-php : clean apt cache ------------------------------------------- 1.67s
ansible-php : create local facts ---------------------------------------- 1.62s
ansible-php : add apt signing key (debian) ------------------------------ 1.58s
ansible-php : do facts module to get latest information ----------------- 1.50s
ansible-php : ensure php-fpm is started and enabled at boot ------------- 1.40s


# after

## run 1

Freitag 06 Januar 2023  06:14:05 +0100 (0:00:01.291)       0:01:24.289 ********
===============================================================================
ansible-php : ensure PHP packages are installed. ----------------------- 23.13s
ansible-php : create php.ini configuration files ------------------------ 7.05s
ansible-php : ensure configuration directories exist -------------------- 4.67s
ansible-php : install dependencies -------------------------------------- 4.38s
ansible-php : update package -------------------------------------------- 3.44s
ansible-php : create php-fpm.conf --------------------------------------- 3.42s
ansible-php : create sury-php source list ------------------------------- 3.02s
ansible-php : update package cache -------------------------------------- 2.82s
ansible-php : create pool configuration --------------------------------- 2.78s
ansible-php : create local facts ---------------------------------------- 2.78s
ansible-php : detect available php version ------------------------------ 2.76s
ansible-php : add apt signing key (debian) ------------------------------ 2.42s
Gathering Facts --------------------------------------------------------- 2.20s
ansible-php : do facts module to get latest information ----------------- 1.65s
ansible-php : ensure php-fpm is started and enabled at boot ------------- 1.54s
ansible-php : configure modules ----------------------------------------- 1.36s
ansible-php : make sure python3-apt is installed (only debian based) ---- 1.33s
ansible-php : do facts module to get latest information ----------------- 1.32s
ansible-php : clean apt cache ------------------------------------------- 1.31s
ansible-php : restart php-fpm ------------------------------------------- 1.29s


## run 2

Freitag 06 Januar 2023  06:15:20 +0100 (0:00:01.831)       0:00:50.815 ********
===============================================================================
ansible-php : ensure configuration directories exist -------------------- 4.41s
ansible-php : create php.ini configuration files ------------------------ 3.41s
ansible-php : update package -------------------------------------------- 3.14s
ansible-php : detect available php version ------------------------------ 2.71s
ansible-php : update package cache -------------------------------------- 2.59s
ansible-php : install dependencies -------------------------------------- 2.32s
ansible-php : make sure python3-apt is installed (only debian based) ---- 2.29s
ansible-php : ensure PHP packages are installed. ------------------------ 2.28s
Gathering Facts --------------------------------------------------------- 2.13s
ansible-php : create sury-php source list ------------------------------- 1.99s
ansible-php : create local facts ---------------------------------------- 1.83s
ansible-php : create pool configuration --------------------------------- 1.79s
ansible-php : clean apt cache ------------------------------------------- 1.75s
ansible-php : add apt signing key (debian) ------------------------------ 1.69s
ansible-php : create php-fpm.conf --------------------------------------- 1.68s
ansible-php : do facts module to get latest information ----------------- 1.50s
ansible-php : ensure php-fpm is started and enabled at boot ------------- 1.42s
ansible-php : do facts module to get latest information ----------------- 1.36s
ansible-php : configure modules ----------------------------------------- 1.30s
ansible-php : find primary group for user 'www-data' -------------------- 1.24s

