from enum import Enum
TorrentStatus = Enum('TorrentStatus', ('Downloading', 'Uploading', 'Checking', 'Queued', 'Paused', 'Stopped', 'Pending', 'Error', 'Unknown'))