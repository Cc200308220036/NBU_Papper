# 原始数据位置说明

生成器默认读取仓库根目录`raw/`中的不可变原始数据：

- `../../raw/bed_bpp/bed-bpp_v1.json`
- `../../raw/mixed_pallet_boxes/MixedPalletBoxes-v1.0/`

为了避免重复存放大文件，本目录不复制原始数据。生成后的
`provenance/manifest.json`会记录原始数据的绝对路径、SHA-256以及
MixedPalletBoxes的Git提交版本。
