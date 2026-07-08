DELIMITER //
DROP PROCEDURE IF EXISTS users_info_db.get_all_items;
CREATE PROCEDURE users_info_db.get_all_items()
BEGIN
SELECT * from users_info_db.t1;
END //
DELIMITER ;
