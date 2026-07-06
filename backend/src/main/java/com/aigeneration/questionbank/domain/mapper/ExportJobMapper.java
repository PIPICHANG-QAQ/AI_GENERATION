package com.aigeneration.questionbank.domain.mapper;

import com.aigeneration.questionbank.domain.entity.ExportJobEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 导出任务表访问 Mapper。
 *
 * <p>继承 MyBatis Plus {@link BaseMapper}，提供 {@link ExportJobEntity} 的基础 CRUD 能力。</p>
 */
@Mapper
public interface ExportJobMapper extends BaseMapper<ExportJobEntity> {
}
