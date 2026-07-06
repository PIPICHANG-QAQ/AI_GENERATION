package com.aigeneration.questionbank.domain.mapper;

import com.aigeneration.questionbank.domain.entity.StorageFileEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 文件存储元数据表访问 Mapper。
 *
 * <p>继承 MyBatis Plus {@link BaseMapper}，提供 {@link StorageFileEntity} 的基础 CRUD 能力。</p>
 */
@Mapper
public interface StorageFileMapper extends BaseMapper<StorageFileEntity> {
}
