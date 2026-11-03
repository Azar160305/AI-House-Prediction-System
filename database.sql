CREATE DATABASE IF NOT EXISTS smart_house CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE smart_house;

CREATE TABLE users (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL, full_name VARCHAR(150) NULL, email VARCHAR(160) NOT NULL UNIQUE, phone VARCHAR(25) NULL, password_hash VARCHAR(255) NOT NULL, is_admin BOOLEAN NOT NULL DEFAULT FALSE, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE admins (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL UNIQUE, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE house_categories (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(80) NOT NULL UNIQUE, bedrooms INT NOT NULL DEFAULT 0, bathrooms INT NOT NULL DEFAULT 1, area INT NOT NULL DEFAULT 800, base_cost INT NOT NULL DEFAULT 2000000, description TEXT);
CREATE TABLE house_designs (id INT AUTO_INCREMENT PRIMARY KEY, category_id INT NOT NULL, title VARCHAR(120) NOT NULL, floor_plan_json JSON, FOREIGN KEY (category_id) REFERENCES house_categories(id) ON DELETE CASCADE);
CREATE TABLE land_details (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, details JSON NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE water_level_records (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, level_m DECIMAL(8,2) NOT NULL, borewell_depth_m DECIMAL(8,2), rainfall_mm DECIMAL(8,2), location VARCHAR(160), recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE house_predictions (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, inputs JSON NOT NULL, result JSON NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE construction_costs (id INT AUTO_INCREMENT PRIMARY KEY, region VARCHAR(100) NOT NULL UNIQUE, rate_sqft INT NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP);
CREATE TABLE saved_designs (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, category_id INT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE KEY user_design (user_id, category_id), FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY (category_id) REFERENCES house_categories(id) ON DELETE CASCADE);
CREATE TABLE chat_history (id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE construction_materials (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(80) NOT NULL UNIQUE, unit VARCHAR(40) NOT NULL, unit_price DECIMAL(10,2) NOT NULL DEFAULT 0);

INSERT INTO house_categories(name,bedrooms,bathrooms,area,base_cost,description) VALUES
('1BHK House',1,1,550,1400000,'Illustrative planning profile'),('2BHK House',2,2,900,2300000,'Illustrative planning profile'),('3BHK House',3,2,1350,3500000,'Illustrative planning profile'),('4BHK House',4,3,1900,5100000,'Illustrative planning profile'),('Individual Villa',3,3,1800,6000000,'Illustrative planning profile'),('Duplex House',4,3,2100,6500000,'Illustrative planning profile'),('Independent House',3,2,1450,3900000,'Illustrative planning profile'),('Apartment',2,2,1000,2600000,'Illustrative planning profile');
INSERT INTO construction_materials(name,unit,unit_price) VALUES ('Cement','50 kg bag',390),('Steel','kg',68),('Sand','cubic ft',55),('Brick','piece',12);
