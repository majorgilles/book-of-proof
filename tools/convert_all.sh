#!/bin/sh
# slug first-page last-page (0-based PDF indices; part title pages go with the chapter that follows)
set -e
while read slug a b s1 s2; do
  python tools/convert.py "$slug" "$a" "$b" $s1 $s2
done <<LIST
front 0 13 3 5
ch01 14 44
ch02 45 75
ch03 76 121
ch04 122 138
ch05 139 147
ch06 148 155
ch07 156 167
ch08 168 182
ch09 183 190
ch10 191 209
ch11 210 233
ch12 234 254
ch13 255 279
ch14 280 301
conclusion 302 302
solutions 303 374
LIST
