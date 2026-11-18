%% UR10不同标定/摩擦组合的统一对比与误差分析
% Python负责MuJoCo逆动力学和组合数据导出；本脚本只选择组合、计算指标和绘图。
% 每条轨迹固定输出三种样式：电流对比、力矩对比、力矩误差。

close all; clear; clc;

%% 切换实验
script_dir = fileparts(mfilename('fullpath'));
data_dir = fullfile(script_dir, '..', 'outputs', 'results_all_combinations');
figure_dir = fullfile(script_dir, '..', 'outputs', 'matlab_figures_combinations');
if ~exist(figure_dir, 'dir'); mkdir(figure_dir); end

trajectory_numbers = 0;    % 例如：0、4、[0 3 7]或0:9

% 可选实验模式：
% "full_model_comparison"      原始完整模型 vs 完整标定模型
% "identified_friction_effect" 标定刚体下：无摩擦 vs 辨识非线性摩擦
% "rigid_parameter_effect"      无摩擦下：原始刚体 vs 标定刚体
% "nominal_friction_effect"     原始刚体下：无摩擦 vs 辨识非线性摩擦
% "xml_default_friction_effect" 标定刚体下：原始XML默认摩擦 vs 辨识非线性摩擦
% "custom"                      使用下面custom_case_1和custom_case_2自由组合
experiment_mode = "xml_default_friction_effect";

% custom模式可用名称：nominal_xml、nominal_off、nominal_identified_friction、
% identified_off、identified_xml_default、identified_nonlinear
custom_case_1 = "nominal_xml";
custom_case_2 = "identified_nonlinear";

show_figures = true;       % false：后台绘图但仍保存
save_png = true;
export_metrics_csv = true;
image_resolution = 200;
% 图窗按屏幕比例显示，避免固定像素尺寸使标题栏超出屏幕。
% 格式：[左边距 下边距 宽度 高度]，取值范围0~1。
figure_position = [0.07 0.10 0.86 0.78];

% 三种图可按需要关闭，但默认全部生成。
plot_current = true;
plot_torque = true;
plot_torque_error = true;

% 可选辅助处理。默认关闭，解除时只改false为true，不要改后面的绘图代码。
show_target_moment = false; % 仅在力矩图辅助显示UR target_moment
use_raw_current = false;    % true仅用于检查原始电流；正式比较建议保持false

%% 二、逐轨迹选择组合并处理
for trajectory = trajectory_numbers
    result_file = fullfile(data_dir, ...
        sprintf('trajectory_%d_all_combinations.mat', trajectory));
    if ~isfile(result_file)
        error(['找不到组合结果：%s\n请先运行', ...
            'ur10_all_model_combinations.py'], result_file);
    end
    data = load(result_file);
    t = data.time_s(:);

    if use_raw_current
        actual_current = data.actual_current_raw_A;
        current_reference_text = '真机原始实际电流';
    else
        actual_current = data.actual_current_filtered_A;
        current_reference_text = '真机滤波实际电流';
    end
    % 正式力矩参考始终由滤波电流换算，避免原始噪声改变动力学误差结论。
    actual_torque = data.actual_torque_est_from_filtered_current_Nm;

    [case_1, case_2] = mode_to_cases( ...
        experiment_mode, custom_case_1, custom_case_2);
    [current_1, torque_1, label_1, short_1] = select_case(data, case_1);
    [current_2, torque_2, label_2, short_2] = select_case(data, case_2);
    title_label_1 = case_short_label(case_1);
    title_label_2 = case_short_label(case_2);

    visibility = 'off';
    if show_figures; visibility = 'on'; end

    %% 三、误差指标：每条轨迹、每个关节、每个模型分别计算
    for joint = 1:6
        row_1 = make_metric_row(trajectory, joint, short_1, ...
            torque_1(:,joint), actual_torque(:,joint));
        row_2 = make_metric_row(trajectory, joint, short_2, ...
            torque_2(:,joint), actual_torque(:,joint));
        if joint == 1
            metrics_rows = [row_1; row_2];
        else
            metrics_rows = [metrics_rows; row_1; row_2]; %#ok<AGROW>
        end
    end

    %% 四、电流对比图
    if plot_current
        fig_current = figure('Visible', visibility, 'Color', 'w', ...
            'Name', sprintf('轨迹%d－电流对比', trajectory), ...
            'Units', 'normalized', 'Position', figure_position);
        layout = tiledlayout(fig_current, 3, 2, ...
            'TileSpacing', 'compact', 'Padding', 'compact');
        for joint = 1:6
            ax = nexttile(layout, joint);
            plot(ax, t, actual_current(:,joint), 'k-', 'LineWidth', 1.2, ...
                'DisplayName', current_reference_text); hold(ax, 'on');
            plot(ax, t, current_1(:,joint), '-', 'Color', [0.466 0.674 0.188], ...
                'LineWidth', 1.0, 'DisplayName', label_1);
            plot(ax, t, current_2(:,joint), '-', 'Color', [0 0.447 0.741], ...
                'LineWidth', 1.1, 'DisplayName', label_2); hold(ax, 'off');
            rmse_1 = sqrt(mean((current_1(:,joint)-actual_current(:,joint)).^2));
            rmse_2 = sqrt(mean((current_2(:,joint)-actual_current(:,joint)).^2));
            grid(ax, 'on'); box(ax, 'on');
            xlabel(ax, '时间（s）'); ylabel(ax, '电流（A）');
            title(ax, sprintf('关节%d RMSE：%s %.4f；%s %.4f A', ...
                joint, title_label_1, rmse_1, title_label_2, rmse_2));
            if joint == 1; legend(ax, 'Location', 'best'); end
        end
        title(layout, sprintf('轨迹%d：%s', trajectory, mode_title(experiment_mode)), ...
            'FontWeight', 'bold');
    end

    %% 五、力矩对比图
    if plot_torque
        fig_torque = figure('Visible', visibility, 'Color', 'w', ...
            'Name', sprintf('轨迹%d－力矩对比', trajectory), ...
            'Units', 'normalized', 'Position', figure_position);
        layout = tiledlayout(fig_torque, 3, 2, ...
            'TileSpacing', 'compact', 'Padding', 'compact');
        for joint = 1:6
            ax = nexttile(layout, joint);
            plot(ax, t, actual_torque(:,joint), 'k-', 'LineWidth', 1.2, ...
                'DisplayName', '真机估算力矩（K_t I）'); hold(ax, 'on');
            plot(ax, t, torque_1(:,joint), '-', 'Color', [0.466 0.674 0.188], ...
                'LineWidth', 1.0, 'DisplayName', label_1);
            plot(ax, t, torque_2(:,joint), '-', 'Color', [0 0.447 0.741], ...
                'LineWidth', 1.1, 'DisplayName', label_2);
            if show_target_moment
                plot(ax, t, data.target_moment_Nm(:,joint), '--', ...
                    'Color', [0.5 0.5 0.5], 'DisplayName', 'UR target moment');
            end
            hold(ax, 'off');
            rmse_1 = sqrt(mean((torque_1(:,joint)-actual_torque(:,joint)).^2));
            rmse_2 = sqrt(mean((torque_2(:,joint)-actual_torque(:,joint)).^2));
            grid(ax, 'on'); box(ax, 'on');
            xlabel(ax, '时间（s）'); ylabel(ax, '力矩（N·m）');
            title(ax, sprintf('关节%d RMSE：%s %.3f；%s %.3f N·m', ...
                joint, title_label_1, rmse_1, title_label_2, rmse_2));
            if joint == 1; legend(ax, 'Location', 'best'); end
        end
        title(layout, sprintf('轨迹%d：%s', trajectory, mode_title(experiment_mode)), ...
            'FontWeight', 'bold');
    end

    %% 六、力矩误差图
    if plot_torque_error
        error_1 = torque_1 - actual_torque;
        error_2 = torque_2 - actual_torque;
        fig_error = figure('Visible', visibility, 'Color', 'w', ...
            'Name', sprintf('轨迹%d－力矩误差', trajectory), ...
            'Units', 'normalized', 'Position', figure_position);
        layout = tiledlayout(fig_error, 3, 2, ...
            'TileSpacing', 'compact', 'Padding', 'compact');
        for joint = 1:6
            ax = nexttile(layout, joint);
            yline(ax, 0, 'k-', 'LineWidth', 0.7, ...
                'HandleVisibility', 'off'); hold(ax, 'on');
            plot(ax, t, error_1(:,joint), '-', 'Color', [0.466 0.674 0.188], ...
                'LineWidth', 1.0, 'DisplayName', [label_1 '误差']);
            plot(ax, t, error_2(:,joint), '-', 'Color', [0 0.447 0.741], ...
                'LineWidth', 1.1, 'DisplayName', [label_2 '误差']); hold(ax, 'off');
            grid(ax, 'on'); box(ax, 'on');
            xlabel(ax, '时间（s）'); ylabel(ax, '力矩误差（N·m）');
            title(ax, sprintf('关节%d Bias：%s %.3f；%s %.3f N·m', ...
                joint, title_label_1, mean(error_1(:,joint)), ...
                title_label_2, mean(error_2(:,joint))));
            if joint == 1; legend(ax, 'Location', 'best'); end
        end
        title(layout, sprintf('轨迹%d：力矩误差（模型－真机估算值）', trajectory), ...
            'FontWeight', 'bold');
    end

    %% 七、保存图片与误差指标表
    file_prefix = sprintf('trajectory_%d_%s', trajectory, experiment_mode);
    if save_png
        if plot_current
            exportgraphics(fig_current, fullfile(figure_dir, ...
                [file_prefix '_current.png']), 'Resolution', image_resolution);
        end
        if plot_torque
            exportgraphics(fig_torque, fullfile(figure_dir, ...
                [file_prefix '_torque.png']), 'Resolution', image_resolution);
        end
        if plot_torque_error
            exportgraphics(fig_error, fullfile(figure_dir, ...
                [file_prefix '_torque_error.png']), 'Resolution', image_resolution);
        end
    end
    if export_metrics_csv
        writetable(metrics_rows, fullfile(figure_dir, ...
            [file_prefix '_torque_metrics.csv']));
    end
    if ~show_figures
        if plot_current; close(fig_current); end
        if plot_torque; close(fig_torque); end
        if plot_torque_error; close(fig_error); end
    end
end

fprintf('处理完成。输出目录：%s\n', figure_dir);

%% 八、局部函数：集中管理组合名称，避免手工替换变量时混淆
function [case_1, case_2] = mode_to_cases(mode, custom_1, custom_2)
switch mode
    case "full_model_comparison"
        case_1 = "nominal_xml"; case_2 = "identified_nonlinear";
    case "identified_friction_effect"
        case_1 = "identified_off"; case_2 = "identified_nonlinear";
    case "rigid_parameter_effect"
        case_1 = "nominal_off"; case_2 = "identified_off";
    case "nominal_friction_effect"
        case_1 = "nominal_off"; case_2 = "nominal_identified_friction";
    case "xml_default_friction_effect"
        case_1 = "identified_xml_default"; case_2 = "identified_nonlinear";
    case "custom"
        case_1 = custom_1; case_2 = custom_2;
    otherwise
        error('未知experiment_mode：%s', mode);
end
end

function [current, torque, label, short_name] = select_case(data, case_name)
switch case_name
    case "nominal_xml"
        current = data.nominal_rigid_original_xml_friction_current_A;
        torque = data.nominal_rigid_original_xml_friction_torque_Nm;
        label = '原始刚体＋原始XML摩擦'; short_name = "nominal_xml";
    case "nominal_off"
        current = data.nominal_rigid_friction_off_current_A;
        torque = data.nominal_rigid_friction_off_torque_Nm;
        label = '原始刚体＋无摩擦'; short_name = "nominal_off";
    case "nominal_identified_friction"
        current = data.nominal_rigid_identified_nonlinear_friction_current_A;
        torque = data.nominal_rigid_identified_nonlinear_friction_torque_Nm;
        label = '原始刚体＋辨识非线性摩擦'; short_name = "nominal_id_friction";
    case "identified_off"
        current = data.identified_rigid_friction_off_current_A;
        torque = data.identified_rigid_friction_off_torque_Nm;
        label = '标定刚体＋无摩擦'; short_name = "identified_off";
    case "identified_xml_default"
        current = data.identified_rigid_original_xml_friction_current_A;
        torque = data.identified_rigid_original_xml_friction_torque_Nm;
        label = '标定刚体＋原始XML默认摩擦'; short_name = "identified_xml_default";
    case "identified_nonlinear"
        current = data.identified_rigid_identified_nonlinear_friction_current_A;
        torque = data.identified_rigid_identified_nonlinear_friction_torque_Nm;
        label = '标定刚体＋辨识非线性摩擦'; short_name = "identified_nonlinear";
    otherwise
        error('未知组合名称：%s', case_name);
end
end

function text = mode_title(mode)
switch mode
    case "full_model_comparison"; text = '原始完整模型与完整标定模型对比';
    case "identified_friction_effect"; text = '标定刚体参数下的摩擦模型对比';
    case "rigid_parameter_effect"; text = '无摩擦条件下的刚体参数对比';
    case "nominal_friction_effect"; text = '原始刚体参数下的摩擦模型对比';
    case "xml_default_friction_effect"; text = '原始XML默认摩擦与非线性摩擦对比';
    otherwise; text = '自定义模型组合对比';
end
end

function text = case_short_label(case_name)
switch case_name
    case "nominal_xml"; text = '原始完整';
    case "nominal_off"; text = '原始无摩擦';
    case "nominal_identified_friction"; text = '原始＋辨识摩擦';
    case "identified_off"; text = '标定无摩擦';
    case "identified_xml_default"; text = 'XML默认摩擦';
    case "identified_nonlinear"; text = '完整标定';
    otherwise; text = char(case_name);
end
end

function row = make_metric_row(trajectory, joint, model, predicted, measured)
error_value = predicted - measured;
rmse = sqrt(mean(error_value.^2));
mae = mean(abs(error_value));
bias = mean(error_value);
max_abs_error = max(abs(error_value));
sst = sum((measured-mean(measured)).^2);
if sst > 0; r2 = 1-sum(error_value.^2)/sst; else; r2 = NaN; end
row = table(trajectory, joint, model, rmse, mae, bias, max_abs_error, r2, ...
    'VariableNames', {'trajectory','joint','model','rmse_Nm','mae_Nm', ...
    'bias_Nm','max_abs_error_Nm','r2'});
end
