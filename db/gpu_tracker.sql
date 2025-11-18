-- -----------------------------------------------------
-- Database microcenter_gpu_tracker
-- -----------------------------------------------------
CREATE DATABASE IF NOT EXISTS `microcenter_gpu_tracker` DEFAULT CHARACTER SET utf8mb4 ;
USE `microcenter_gpu_tracker` ;

-- -----------------------------------------------------
-- Table `stores`
--
-- Stores a list of all Micro Center store locations
-- you are tracking.
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `stores` (
  `store_id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(100) NOT NULL COMMENT 'e.g., \"Overland Park\" or \"Tustin\"',
  `city` VARCHAR(100) NOT NULL,
  `state` CHAR(2) NOT NULL COMMENT 'e.g., \"KS\" or \"CA\"',
  PRIMARY KEY (`store_id`),
  UNIQUE INDEX `idx_store_location` (`name` ASC, `city` ASC, `state` ASC) COMMENT 'Ensures we don\'t add the same store twice.'
)
ENGINE = InnoDB
COMMENT = 'List of Micro Center store locations to track.';


-- -----------------------------------------------------
-- Table `gpus`
--
-- Stores the master list of all unique GPU models.
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `gpus` (
  `gpu_id` INT NOT NULL AUTO_INCREMENT,
  `brand` VARCHAR(45) NULL COMMENT 'e.g., \"NVIDIA\", \"AMD\", \"Intel\"',
  `model_name` VARCHAR(100) NOT NULL COMMENT 'e.g., \"GeForce RTX 4090\"',
  `manufacturer` VARCHAR(100) NULL COMMENT 'e.g., \"ASUS\", \"MSI\", \"Gigabyte\"',
  `full_name` VARCHAR(255) NOT NULL COMMENT 'The full product name, e.g., \"ASUS NVIDIA GeForce RTX 4090 TUF Gaming OC\"',
  PRIMARY KEY (`gpu_id`),
  UNIQUE INDEX `idx_full_name` (`full_name` ASC) COMMENT 'Ensures we don\'t add the same GPU model twice.'
)
ENGINE = InnoDB
COMMENT = 'Master list of unique GPU models being tracked.';


-- -----------------------------------------------------
-- Table `products`
--
-- This is the main \"join\" table. It links a specific GPU
-- to a specific Store and stores the unique identifiers
-- for that product listing (like SKU and URL).
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `products` (
  `product_id` INT NOT NULL AUTO_INCREMENT,
  `store_id` INT NOT NULL COMMENT 'Foreign key to the `stores` table.',
  `gpu_id` INT NOT NULL COMMENT 'Foreign key to the `gpus` table.',
  `microcenter_sku` VARCHAR(45) NOT NULL COMMENT 'The unique SKU from the Micro Center website.',
  `product_url` VARCHAR(2048) NULL COMMENT 'The direct URL to the product page.',
  `last_seen_image_url` VARCHAR(2048) NULL COMMENT 'URL of the product image, updated as needed.',
  PRIMARY KEY (`product_id`),
  UNIQUE INDEX `idx_sku` (`microcenter_sku` ASC) COMMENT 'The SKU should be unique across all stores.',
  INDEX `fk_products_stores_idx` (`store_id` ASC),
  INDEX `fk_products_gpus_idx` (`gpu_id` ASC),
  CONSTRAINT `fk_products_stores`
    FOREIGN KEY (`store_id`)
    REFERENCES `stores` (`store_id`)
    ON DELETE RESTRICT
    ON UPDATE CASCADE,
  CONSTRAINT `fk_products_gpus`
    FOREIGN KEY (`gpu_id`)
    REFERENCES `gpus` (`gpu_id`)
    ON DELETE RESTRICT
    ON UPDATE CASCADE
)
ENGINE = InnoDB
COMMENT = 'Links a specific GPU to a specific Store with its unique SKU.';


-- -----------------------------------------------------
-- Table `price_history`
--
-- This is the log table. Every time the scraper runs,
-- it will add a new row here for each product it
-- checks.
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `price_history` (
  `history_id` BIGINT NOT NULL AUTO_INCREMENT,
  `product_id` INT NOT NULL COMMENT 'Foreign key to the `products` table.',
  `price_usd` DECIMAL(10,2) NOT NULL COMMENT 'The price of the item at the time of scraping.',
  `stock_status` VARCHAR(50) NOT NULL COMMENT 'e.g., \"In Stock\", \"Out of Stock\", \"Sold Out\"',
  `scraped_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'The timestamp when this data was recorded.',
  PRIMARY KEY (`history_id`),
  INDEX `fk_price_history_products_idx` (`product_id` ASC),
  INDEX `idx_scraped_at` (`scraped_at` DESC) COMMENT 'To quickly find the most recent entries.',
  CONSTRAINT `fk_price_history_products`
    FOREIGN KEY (`product_id`)
    REFERENCES `products` (`product_id`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
)
ENGINE = InnoDB
COMMENT = 'A time-series log of price and stock for each product.';