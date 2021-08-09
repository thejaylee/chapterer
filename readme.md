## Video Chapter Creator

A very simple python tkinter app for creating chapter files for videos

#### Hotkeys

- CTRL + S
  - save the current chapter file
- CTRL + W
  - close the current video file
- CTRL + R
  - run the script (see script section)

#### Output

The chapter file generated will be generated as "[video filename].chapters.txt" with the following format:

```
CHAPTER##=hh:mm:ss.fff
CHAPTER##NAME=<chapter name>
...
```
#### Script

An optional argument may be passed in which will a command to run via `CTRL + R`.

The command will receive 2 parameters:

- The full file path of the video file
- The full file path of the chapter file
