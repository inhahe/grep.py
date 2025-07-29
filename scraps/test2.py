import configparser
config = configparser.ConfigParser()
print(config.read("test.conf"))
print(config["colors"])





