# Python4Property

这个仓库包含 CO2 物性表生成脚本，用于调用 CoolProp 生成不同压力、温度下的真实气体物性数据。当前包括两类输出格式：一种是长表 CSV，另一种是 Fluent UDF 插值更方便使用的二维矩阵表。

## 文件

- `CO2_property_table.py`：长表格式，来自 `CO2_STARCCM2.jl` 的 Python 改写版本。
- `CO2_property_2Dtable.py`：二维矩阵格式，来自 `create_CO2_properties.jl` 的 Python 改写版本，适合 Fluent UDF 插值表。
- `validate_CO2_2Dtable.py`：二维表验证脚本，对比 CSV 双线性插值结果与 CoolProp 直接查询结果，并输出误差统计和图。

## 依赖

```powershell
pip install CoolProp
pip install matplotlib
```

生成脚本只依赖 Python 标准库和 CoolProp，不强制依赖 pandas 或 numpy。验证脚本需要 `matplotlib` 用于输出图片。

## 长表脚本：CO2_property_table.py

### 默认参数

默认网格与原 Julia 脚本保持一致：

- 温度：220-1500 K，共 1500 个点
- 压力：0.05-40 MPa，共 1000 个点
- 流体：CO2
- 输出：`CO2.csv`

这些默认值集中写在 `CO2_property_table.py` 顶部：

```python
DEFAULT_T_MAX = 1500.0
DEFAULT_P_MAX = 40.0e6
DEFAULT_T_COUNT = 1500
DEFAULT_P_COUNT = 1000
DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) - 1)
```

如果在 PyCharm 中直接点击运行，不想配置命令行参数，可以直接修改这些默认变量。若同时设置了命令行参数，则命令行参数会覆盖顶部默认值。

输出字段：

| 字段 | 含义 |
|---|---|
| Pressure | 压力，Pa |
| Temperature | 温度，K |
| Density | 密度，kg/m3 |
| Viscosity | 动力黏度，Pa s |
| Entropy | 比熵，J/(kg K) |
| Enthalpy | 比焓，J/kg |
| SpecificHeatCapacity | 定压比热，J/(kg K) |
| Cv | 定容比热，J/(kg K) |
| Gamma | 比热比，Cp/Cv |
| ThermalConductivity | 导热率，W/(m K) |
| SpeedOfSound | 声速，m/s |

### 运行方式

在当前文件夹中运行：

```powershell
python CO2_property_table.py
```

指定输出文件和并行进程数：

```powershell
python CO2_property_table.py --output CO2.csv --workers 8
```

在 PyCharm 的 Run/Debug Configuration 中，也可以在 Parameters 中填写同样的参数，例如：

```powershell
--t-count 20 --p-count 20 --output CO2_test.csv --workers 4
```

减少网格点数用于测试：

```powershell
python CO2_property_table.py --t-count 20 --p-count 20 --output CO2_test.csv --workers 4
```

指定新的压力、温度范围：

```powershell
python CO2_property_table.py --t-min 300 --t-max 900 --t-count 500 --p-min 1000000 --p-max 25000000 --p-count 600 --output CO2_custom.csv
```

### 与 Julia 版本的主要区别

1. 使用 Python `ProcessPoolExecutor` 并行计算。每个任务负责一个温度行下的所有压力点，适合 CoolProp 这种计算量较重的函数调用。
2. 计算结果直接流式写入 CSV，避免一次性把 150 万个状态点全部堆在内存中。
3. 失败状态点会写入 `CO2_property_errors.log`，便于检查是否有跨相区、物性失败或输入范围问题。
4. 写入顺序按并行任务完成顺序输出。如果需要完全按温度、压力排序，可在后处理时按 `Temperature, Pressure` 排序。

## Fluent 二维表脚本：CO2_property_2Dtable.py

`CO2_property_2Dtable.py` 会生成 4 个 CSV 文件：

| 文件 | 物性 |
|---|---|
| `co2_density.csv` | 密度，kg/m3 |
| `co2_viscosity.csv` | 动力黏度，Pa s |
| `co2_cp.csv` | 定压比热，J/(kg K) |
| `co2_conductivity.csv` | 导热率，W/(m K) |

每个 CSV 都采用二维矩阵格式：第一列为压力，第一行为温度。脚本内部仍使用 Pa 调用 CoolProp，输出 CSV 的第一列压力换算为 MPa。结构如下：

```text
P(MPa)/T(K),220.0,220.5,221.0,...
0.05,value,value,value,...
0.15,value,value,value,...
```

默认网格与 `create_CO2_properties.jl` 保持一致：

- 温度：220-1500 K，步长 0.5 K
- 计算压力：50000-40000000 Pa，步长 100000 Pa
- CSV 输出压力：0.05-39.95 MPa，步长 0.1 MPa
- 流体：CO2

这些默认值集中写在 `CO2_property_2Dtable.py` 顶部：

```python
DEFAULT_T_MAX = 1500.0
DEFAULT_T_STEP = 0.5
DEFAULT_P_MAX = 40_000_000.0
DEFAULT_P_STEP = 100_000.0
DEFAULT_WORKERS = max(1, (os.cpu_count() or 2) - 1)
DEFAULT_GRID_MODE = "uniform"
```

直接运行：

```powershell
python CO2_property_2Dtable.py
```

默认使用全区间等步长模式：

```powershell
python CO2_property_2Dtable.py --grid-mode uniform
```

如果希望在 CO2 临界区附近单独加密，可以使用 `critical` 模式。脚本会先生成全区间基础网格，再把临界区细网格合并进去并排序去重：

```powershell
python CO2_property_2Dtable.py --grid-mode critical
```

临界区加密参数也可以单独指定。例如，在 300-310 K、7-8 MPa 附近加密：

```powershell
python CO2_property_2Dtable.py --grid-mode critical --critical-t-min 300 --critical-t-max 310 --critical-t-step 0.05 --critical-p-min 7000000 --critical-p-max 8000000 --critical-p-step 10000
```

如果只想覆盖较小范围并加密临界区，可以这样测试：

```powershell
python CO2_property_2Dtable.py --grid-mode critical --t-min 295 --t-max 315 --t-step 2 --p-min 6000000 --p-max 9000000 --p-step 500000 --critical-t-min 302 --critical-t-max 306 --critical-t-step 0.1 --critical-p-min 7200000 --critical-p-max 7600000 --critical-p-step 50000 --output-dir critical_test --workers 4
```

指定输出文件夹和并行进程数：

```powershell
python CO2_property_2Dtable.py --output-dir fluent_tables --workers 8
```

用小网格测试：

```powershell
python CO2_property_2Dtable.py --t-min 220 --t-max 230 --t-step 1 --p-min 50000 --p-max 500000 --p-step 50000 --output-dir test_tables --workers 4
```

在 PyCharm 的 Run/Debug Configuration 中，可以在 Parameters 中填写同样的参数，例如：

```powershell
--t-max 900 --p-max 25000000 --t-step 1 --p-step 50000 --output-dir fluent_tables --workers 6
```

临界区加密模式在 PyCharm 中也一样填写到 Parameters 中，例如：

```powershell
--grid-mode critical --critical-t-min 300 --critical-t-max 310 --critical-t-step 0.05 --critical-p-min 7000000 --critical-p-max 8000000 --critical-p-step 10000 --output-dir fluent_tables --workers 6
```

这个脚本使用 Python `ProcessPoolExecutor` 并行计算。每个任务负责一个压力行下的全部温度点，输出时会按压力从小到大排序，便于 Fluent UDF 读取。无论使用 `uniform` 还是 `critical` 模式，输出 CSV 都保持同样的二维表结构，只是温度列和压力行可以变为非均匀间隔。

## 二维表验证脚本：validate_CO2_2Dtable.py

`validate_CO2_2Dtable.py` 用于验证二维 CSV 物性表的插值精度。它会随机抽取温压点，对比：

```text
CoolProp 直接查询值 vs CSV 双线性插值值
```

默认会读取当前文件夹下的 4 个表：

- `co2_density.csv`
- `co2_viscosity.csv`
- `co2_cp.csv`
- `co2_conductivity.csv`

在表格所在文件夹中运行：

```powershell
python validate_CO2_2Dtable.py
```

指定表格目录、输出目录和采样点数：

```powershell
python validate_CO2_2Dtable.py --table-dir fluent_tables --output-dir validation_results --samples 1000 --critical-samples 300
```

在 PyCharm 中，也可以把下面内容填到 Parameters：

```powershell
--table-dir fluent_tables --output-dir validation_results --samples 1000 --critical-samples 300
```

输出文件包括：

| 文件 | 内容 |
|---|---|
| `validation_sample_points.csv` | 验证过程中抽取的温度、压力组合，含 sample_id、区域标签、K、Pa、MPa |
| `coolprop_property_samples.csv` | 每个抽样点的 CoolProp 直接查询物性宽表 |
| `csv_interpolated_property_samples.csv` | 每个抽样点由 CSV 双线性插值得到的物性宽表 |
| `validation_point_errors.csv` | 每个随机点的 CoolProp 值、表格插值值、绝对误差、相对误差 |
| `validation_error_summary.csv` | 每种物性的平均误差、95% 分位误差、最大误差 |
| `validation_report.md` | Markdown 验证报告 |
| `relative_error_boxplot.png` | 四种物性的相对误差箱线图 |
| `relative_error_vs_temperature.png` | 相对误差随温度变化 |
| `relative_error_vs_pressure.png` | 相对误差随压力变化 |
| `critical_region_profile.png` | 临界区附近 CoolProp 与表格插值曲线对比 |

CSV 表第一列压力按 MPa 读取，CoolProp 查询时会自动换算为 Pa。温度单位为 K。

## 给 STAR-CCM+ 或 Fluent 使用时的提醒

如果后续要用于真实气体物性插值表，建议先做小网格测试，确认 CO2 在目标压力温度范围内 CoolProp 没有异常点，再生成完整表格。对于 sCO2-LBE 射流模拟，还建议额外检查临界区附近的密度、声速、Cp 和 Gamma 是否平滑，因为这些量会直接影响阻塞流量、马赫数和激波位置。
